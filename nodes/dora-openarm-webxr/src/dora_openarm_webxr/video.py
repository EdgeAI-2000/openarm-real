# Copyright 2026 Enactic, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Head and gripper camera video downlink for the WebXR front-end.

Takes JPEG images from the robot's head and gripper cameras and forwards
them to the VR device. The stereo head camera is the main view; optional
gripper images are drawn as fixed picture-in-picture panels.

Frames go on their own WebSocket so they never delay the pose messages
that feed IK. How the panel is placed is tuned in
``example/view_camera.yaml``.
"""

import argparse
import asyncio
import os
import pathlib

import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

# dora-rs input IDs mapped to a video stream. A stream is independent of a
# Quest eye: each head stream is rendered by its matching eye, while each
# gripper stream is rendered identically in both eyes as a virtual panel.
CAMERA_INPUTS = {
    "camera_head_left": "head_left",
    "camera_head_right": "head_right",
    "camera_wrist_left": "wrist_left",
    "camera_wrist_right": "wrist_right",
}

# Each frame is sent as a binary WebSocket message prefixed with one byte
# identifying the stream, followed by the JPEG data. Values 0 and 1 retain
# the original head-only protocol so older clients keep working.
STREAM_PREFIX = {
    "head_left": b"\x00",
    "head_right": b"\x01",
    "wrist_left": b"\x02",
    "wrist_right": b"\x03",
}

# Used when no --view-configuration-file is given.
DEFAULT_VIEW_CONFIGURATION: dict = {
    "view": "mono",
    "session": {"mode": "immersive-ar"},
    "panel": {"lock": "room", "distance": 1.3, "width": 1.5},
}

_frames: dict = {stream: None for stream in STREAM_PREFIX}
# Incremented on every frame so that the video endpoint can tell a new
# frame from a repeated one and always send the most recent one.
_sequences: dict = {stream: 0 for stream in STREAM_PREFIX}
_frame_event = asyncio.Event()

_view_configuration: dict = DEFAULT_VIEW_CONFIGURATION


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the head camera options to the node's argument parser."""
    parser.add_argument(
        "--view-configuration-file",
        type=pathlib.Path,
        default=os.getenv("VIEW_CONFIGURATION_FILE"),
        help="YAML file with the head camera panel parameters",
    )


def configure(args: argparse.Namespace) -> None:
    """Read the view configuration at startup if a file was given.

    Read once; restart the dataflow to apply a change.
    """
    path = getattr(args, "view_configuration_file", None)
    if path is None:
        return
    global _view_configuration
    try:
        with open(path, encoding="utf-8") as input:
            _view_configuration = yaml.safe_load(input)
    except (OSError, yaml.YAMLError) as error:
        # Keep the default so a broken file cannot stop the node.
        print(f"cannot read {path}: {error}", flush=True)


def view_configuration() -> dict:
    """Return the view configuration read at startup."""
    return _view_configuration


def handle_event(event) -> bool:
    """Store a head camera frame. Return whether the event was ours."""
    if event["type"] != "INPUT" or event["id"] not in CAMERA_INPUTS:
        return False
    stream = CAMERA_INPUTS[event["id"]]
    # The camera node sends JPEG data as a uint8 array.
    _frames[stream] = event["value"].to_numpy(zero_copy_only=False).tobytes()
    _sequences[stream] += 1
    _frame_event.set()
    return True


def register_routes(app: FastAPI, should_exit) -> None:
    """Register the head camera routes on the node's Web application.

    ``should_exit`` is a callable so this module need not know how the
    node shuts its server down.
    """

    @app.get("/view_configuration")
    async def _view_configuration_endpoint():
        """Serve the camera panel parameters to the WebXR front-end."""
        return _view_configuration

    @app.websocket("/video")
    async def _video_endpoint(websocket: WebSocket):
        await websocket.accept()
        stereo = _view_configuration.get("view") == "stereo"
        head_streams = ["head_left", "head_right"] if stereo else ["head_right"]
        wrist_configuration = _view_configuration.get("wrist_panels", {})
        wrist_streams = (
            ["wrist_left", "wrist_right"]
            if wrist_configuration.get("enabled", False)
            else []
        )
        sent = {stream: -1 for stream in head_streams + wrist_streams}
        try:
            while not should_exit():
                try:
                    await asyncio.wait_for(_frame_event.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    # Loop so shutdown is noticed.
                    continue
                _frame_event.clear()
                # A stereo camera publishes its two halves as consecutive Dora
                # outputs. Send them together only after both advance, so a new
                # left image is never paired with the previous right image.
                if all(_frames[stream] is not None for stream in head_streams) and all(
                    _sequences[stream] != sent[stream] for stream in head_streams
                ):
                    for stream in head_streams:
                        sent[stream] = _sequences[stream]
                        await websocket.send_bytes(
                            STREAM_PREFIX[stream] + _frames[stream]
                        )

                # Gripper cameras are independent of each other and of the
                # stereo pair. A slow or disconnected one must not stall the
                # other panels or the main view.
                for stream in wrist_streams:
                    if (
                        _frames[stream] is not None
                        and _sequences[stream] != sent[stream]
                    ):
                        sent[stream] = _sequences[stream]
                        await websocket.send_bytes(
                            STREAM_PREFIX[stream] + _frames[stream]
                        )
            await websocket.close()
        except WebSocketDisconnect:
            pass
