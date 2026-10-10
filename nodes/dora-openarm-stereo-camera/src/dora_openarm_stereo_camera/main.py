"""Capture a side-by-side UVC stereo camera and publish JPEG eye images."""

import argparse
import os
import pathlib
import re
import sys
import time

import dora
import numpy as np
import pyarrow as pa


def split_stereo_frame(frame: np.ndarray, layout: str) -> tuple[np.ndarray, np.ndarray]:
    """Split one side-by-side BGR image into logical left and right eyes."""
    if frame.ndim != 3 or frame.shape[2] not in (3, 4):
        raise ValueError(f"expected a BGR/BGRA frame, got shape {frame.shape}")
    if frame.shape[1] % 2:
        raise ValueError(f"stereo frame width must be even, got {frame.shape[1]}")
    half = frame.shape[1] // 2
    first = np.ascontiguousarray(frame[:, :half])
    second = np.ascontiguousarray(frame[:, half:])
    if layout == "left-right":
        return first, second
    if layout == "right-left":
        return second, first
    raise ValueError(f"unsupported stereo layout: {layout}")


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _open_camera(cv2, args):
    # OpenCV's Linux wheels accept a numeric V4L2 index more consistently
    # than a /dev/v4l/by-id symlink. Resolve the stable user-facing path only
    # at open time, so hot-plug renumbering does not leak into configuration.
    resolved = args.device.resolve()
    match = re.fullmatch(r"video(\d+)", resolved.name)
    if resolved.parent != pathlib.Path("/dev") or match is None:
        raise RuntimeError(f"{args.device} does not resolve to /dev/videoN")
    capture = cv2.VideoCapture(int(match.group(1)), cv2.CAP_V4L2)
    if not capture.isOpened():
        raise RuntimeError(
            f"cannot open stereo camera {args.device}; check the device path and "
            "make sure no other process is using it"
        )
    capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*args.fourcc))
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, args.eye_width * 2)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    capture.set(cv2.CAP_PROP_FPS, args.fps)
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return capture


def _encode_eye(cv2, image: np.ndarray, quality: int) -> pa.Array:
    encoded, jpeg = cv2.imencode(
        ".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality]
    )
    if not encoded:
        raise RuntimeError("OpenCV failed to encode a camera frame as JPEG")
    return pa.array(jpeg.reshape(-1), type=pa.uint8())


def main() -> None:
    """Run the camera node."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--device",
        default=os.getenv("STEREO_CAMERA_DEVICE", "/dev/camera_head_stereo"),
        type=pathlib.Path,
        help="side-by-side V4L2 device (default: /dev/camera_head_stereo)",
    )
    parser.add_argument(
        "--eye-width",
        default=int(os.getenv("STEREO_EYE_WIDTH", "1280")),
        type=_positive_int,
    )
    parser.add_argument(
        "--height",
        default=int(os.getenv("STEREO_HEIGHT", "720")),
        type=_positive_int,
    )
    parser.add_argument(
        "--fps", default=int(os.getenv("STEREO_FPS", "30")), type=_positive_int
    )
    parser.add_argument(
        "--jpeg-quality",
        default=int(os.getenv("STEREO_JPEG_QUALITY", "80")),
        type=int,
    )
    parser.add_argument(
        "--layout",
        choices=("left-right", "right-left"),
        default=os.getenv("STEREO_LAYOUT", "left-right"),
        help="physical ordering inside the side-by-side frame",
    )
    parser.add_argument(
        "--fourcc",
        default=os.getenv("STEREO_FOURCC", "MJPG"),
        help="four-character V4L2 capture format (default: MJPG)",
    )
    args = parser.parse_args()
    if not 1 <= args.jpeg_quality <= 100:
        parser.error("--jpeg-quality must be between 1 and 100")
    if len(args.fourcc) != 4:
        parser.error("--fourcc must contain exactly four characters")

    try:
        import cv2
    except ImportError as error:
        raise SystemExit(
            "OpenCV is missing; rerun 'bash install.sh core' on the Jetson"
        ) from error

    capture = _open_camera(cv2, args)
    node = dora.Node()
    failures = 0
    frame_index = 0
    expected_shape = (args.height, args.eye_width * 2)
    print(
        f"stereo camera {args.device}: {expected_shape[1]}x{expected_shape[0]} "
        f"at {args.fps} fps, {args.layout}, JPEG quality {args.jpeg_quality}",
        flush=True,
    )
    try:
        for event in node:
            if event["type"] == "STOP":
                break
            if event["type"] != "INPUT" or event["id"] != "tick":
                continue
            captured, frame = capture.read()
            if not captured or frame is None:
                failures += 1
                if failures >= 5:
                    raise RuntimeError(
                        f"lost five consecutive frames from {args.device}"
                    )
                continue
            failures = 0
            actual_shape = frame.shape[:2]
            if actual_shape != expected_shape:
                raise RuntimeError(
                    f"camera returned {actual_shape[1]}x{actual_shape[0]}, expected "
                    f"{expected_shape[1]}x{expected_shape[0]}; choose a supported "
                    "--eye-width/--height mode"
                )
            left, right = split_stereo_frame(frame, args.layout)
            metadata = {
                "encoding": "jpeg",
                "frame_index": frame_index,
                "capture_time_ns": time.time_ns(),
            }
            node.send_output(
                "camera_head_left",
                _encode_eye(cv2, left, args.jpeg_quality),
                metadata,
            )
            node.send_output(
                "camera_head_right",
                _encode_eye(cv2, right, args.jpeg_quality),
                metadata,
            )
            frame_index += 1
    finally:
        capture.release()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"stereo camera error: {error}", file=sys.stderr, flush=True)
        raise
