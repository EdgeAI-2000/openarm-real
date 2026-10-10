"""Receive the network overhead camera's existing ROS JPEG stream for Dora."""

import argparse
import base64
from dataclasses import dataclass
import json
import os
import queue
import threading
import time

import cv2
import dora
import numpy as np
import pyarrow as pa
from websockets.sync.client import connect


@dataclass(frozen=True)
class Frame:
    jpeg: bytes
    received_ns: int
    received_monotonic: float
    source_ns: int
    frame_id: str


def decode_frame(message, received_ns, received_monotonic):
    """Validate a ROS CompressedImage while preserving its original JPEG bytes."""
    if "jpeg" not in message.get("format", "").lower():
        raise ValueError("overhead topic must publish JPEG CompressedImage data")
    data = message["data"]
    jpeg = base64.b64decode(data, validate=True) if isinstance(data, str) else bytes(data)
    if not jpeg.startswith(b"\xff\xd8") or cv2.imdecode(
        np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR
    ) is None:
        raise ValueError("overhead camera supplied an invalid JPEG")
    header = message.get("header", {})
    stamp = header.get("stamp", {})
    source_ns = int(stamp.get("sec", 0)) * 1_000_000_000 + int(stamp.get("nanosec", 0))
    if source_ns <= 0:
        raise ValueError("overhead camera frame is missing its ROS capture timestamp")
    return Frame(jpeg, received_ns, received_monotonic, source_ns, header.get("frame_id", ""))


class FrameReceiver:
    """Subscribe without ROS dependencies; retain only the newest complete frame."""

    def __init__(self, url, topic):
        self.url = url
        self.topic = topic
        self.frames = queue.Queue(maxsize=1)
        self.stopped = threading.Event()
        self.last_error = "waiting for the first frame"
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        self.stopped.set()
        self.thread.join(timeout=4)

    def _run(self):
        last_source_ns = None
        while not self.stopped.is_set():
            try:
                # This local connection must bypass HTTP proxy environment variables.
                with connect(self.url, proxy=None, open_timeout=3, close_timeout=1,
                             max_size=8 * 1024 * 1024) as socket:
                    socket.send(json.dumps({
                        "op": "subscribe", "topic": self.topic,
                        "type": "sensor_msgs/CompressedImage", "queue_length": 1,
                    }))
                    while not self.stopped.is_set():
                        try:
                            raw = socket.recv(timeout=0.5)
                        except TimeoutError:
                            continue
                        received_ns, received_monotonic = time.time_ns(), time.monotonic()
                        response = json.loads(raw)
                        if response.get("op") == "status" and response.get("level") == "error":
                            raise RuntimeError(response.get("msg", "ROS subscription failed"))
                        if response.get("op") != "publish" or response.get("topic") != self.topic:
                            continue
                        frame = decode_frame(response["msg"], received_ns, received_monotonic)
                        if frame.source_ns == last_source_ns:
                            continue
                        last_source_ns = frame.source_ns
                        try:
                            self.frames.get_nowait()
                        except queue.Empty:
                            pass
                        self.frames.put_nowait(frame)
                        self.last_error = ""
                    socket.send(json.dumps({"op": "unsubscribe", "topic": self.topic}))
            except Exception as error:
                self.last_error = f"{type(error).__name__}: {error}"
                self.stopped.wait(0.5)


def positive_seconds(value):
    parsed = float(value)
    if not np.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return parsed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("OVERHEAD_ROSBRIDGE_URL", "ws://127.0.0.1:9091"))
    parser.add_argument("--topic", default=os.getenv("OVERHEAD_IMAGE_TOPIC", "/overhead/color/image_raw/compressed"))
    parser.add_argument("--startup-timeout", type=positive_seconds, default=10.0)
    parser.add_argument("--stale-timeout", type=positive_seconds, default=2.0)
    args = parser.parse_args()

    node = dora.Node()
    receiver = FrameReceiver(args.url, args.topic)
    started = time.monotonic()
    last_received = None
    count = 0
    receiver.start()
    try:
        for event in node:
            if event["type"] == "STOP":
                break
            if event["type"] != "INPUT" or event["id"] != "tick":
                continue
            try:
                frame = receiver.frames.get_nowait()
            except queue.Empty:
                frame = None
            now = time.monotonic()
            if frame is not None and now - frame.received_monotonic <= args.stale_timeout:
                last_received = frame.received_monotonic
                node.send_output("camera_ceiling", pa.array(np.frombuffer(frame.jpeg, dtype=np.uint8)), {
                    "encoding": "jpeg", "timestamp": frame.received_ns,
                    "capture_time_ns": frame.source_ns, "receive_time_ns": frame.received_ns,
                    "frame_index": count, "frame_id": frame.frame_id,
                })
                if count == 0:
                    print(f"overhead camera: {args.topic} via {args.url}; JPEG stream active, "
                          "timestamps use Jetson receive time", flush=True)
                count += 1
            timeout = args.startup_timeout if last_received is None else args.stale_timeout
            reference = started if last_received is None else last_received
            if now - reference > timeout:
                raise RuntimeError(f"overhead camera supplied no fresh frame for {timeout:g}s; "
                                   f"check the D455 sender, overhead receiver and ROS bridge. {receiver.last_error}")
    finally:
        receiver.close()


if __name__ == "__main__":
    main()
