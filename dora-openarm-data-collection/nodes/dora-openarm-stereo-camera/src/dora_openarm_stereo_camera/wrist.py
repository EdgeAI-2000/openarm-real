"""Capture one OpenArm gripper camera and publish JPEG frames."""

import argparse
import os
import pathlib
import re
import sys
import time

import dora

from .main import _encode_eye, _positive_int


def video_index(device: pathlib.Path) -> int:
    """Resolve a stable V4L2 path to the numeric index OpenCV expects."""
    resolved = device.resolve()
    match = re.fullmatch(r"video(\d+)", resolved.name)
    if resolved.parent != pathlib.Path("/dev") or match is None:
        raise RuntimeError(f"{device} does not resolve to /dev/videoN")
    return int(match.group(1))


def _device_for_side(side: str) -> pathlib.Path:
    variable = f"WRIST_CAMERA_{side.upper()}_DEVICE"
    return pathlib.Path(os.getenv(variable, f"/dev/camera_wrist_{side}"))


def _open_camera(cv2, args):
    capture = cv2.VideoCapture(video_index(args.device), cv2.CAP_V4L2)
    if not capture.isOpened():
        raise RuntimeError(
            f"cannot open {args.side} gripper camera {args.device}; check the "
            "device path and make sure no other process is using it"
        )
    capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*args.fourcc))
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    capture.set(cv2.CAP_PROP_FPS, args.fps)
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return capture


def main() -> None:
    """Run one gripper-camera node."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--side", required=True, choices=("left", "right"))
    parser.add_argument("--device", type=pathlib.Path)
    parser.add_argument("--width", default=960, type=_positive_int)
    parser.add_argument("--height", default=600, type=_positive_int)
    parser.add_argument("--fps", default=30, type=_positive_int)
    parser.add_argument("--jpeg-quality", default=70, type=int)
    parser.add_argument(
        "--fourcc",
        default="YUYV",
        help="four-character V4L2 capture format (default: YUYV)",
    )
    args = parser.parse_args()
    if args.device is None:
        args.device = _device_for_side(args.side)
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
    output = f"camera_wrist_{args.side}"
    expected_shape = (args.height, args.width)
    failures = 0
    frame_index = 0
    print(
        f"{args.side} gripper camera {args.device}: {args.width}x{args.height} "
        f"at {args.fps} fps, JPEG quality {args.jpeg_quality}",
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
                    "--width/--height mode"
                )
            metadata = {
                "encoding": "jpeg",
                "frame_index": frame_index,
                "capture_time_ns": time.time_ns(),
            }
            node.send_output(
                output,
                _encode_eye(cv2, frame, args.jpeg_quality),
                metadata,
            )
            frame_index += 1
    finally:
        capture.release()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"gripper camera error: {error}", file=sys.stderr, flush=True)
        raise
