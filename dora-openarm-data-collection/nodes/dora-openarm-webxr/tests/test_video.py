"""Tests for the multi-camera WebSocket video downlink."""

import asyncio
import unittest

import numpy as np
from fastapi import FastAPI

from dora_openarm_webxr import video


class _Value:
    def __init__(self, payload):
        self._payload = np.frombuffer(payload, dtype=np.uint8)

    def to_numpy(self, zero_copy_only=False):
        return self._payload


class _WebSocket:
    def __init__(self):
        self.accepted = False
        self.closed = False
        self.messages = []

    async def accept(self):
        self.accepted = True

    async def send_bytes(self, message):
        self.messages.append(message)

    async def close(self):
        self.closed = True


class VideoRouteTest(unittest.TestCase):
    """Exercise one complete four-stream WebSocket send cycle."""

    def setUp(self):
        """Reset the process-global latest-frame buffers."""
        video._frames.update({stream: None for stream in video.STREAM_PREFIX})
        video._sequences.update({stream: 0 for stream in video.STREAM_PREFIX})
        video._frame_event.clear()
        video._view_configuration = {
            "view": "stereo",
            "wrist_panels": {"enabled": True},
        }

    def test_stereo_and_gripper_frames_use_distinct_prefixes(self):
        """Keep the original eye IDs and add unique gripper stream IDs."""
        for input_id in video.CAMERA_INPUTS:
            handled = video.handle_event(
                {
                    "type": "INPUT",
                    "id": input_id,
                    "value": _Value(input_id.encode()),
                }
            )
            self.assertTrue(handled)

        app = FastAPI()
        websocket = _WebSocket()
        video.register_routes(app, lambda: len(websocket.messages) == 4)
        endpoint = next(
            route.endpoint for route in app.routes if route.path == "/video"
        )
        asyncio.run(endpoint(websocket))

        self.assertTrue(websocket.accepted)
        self.assertTrue(websocket.closed)
        self.assertEqual(
            [message[0] for message in websocket.messages],
            [0, 1, 2, 3],
        )
        self.assertEqual(websocket.messages[2][1:], b"camera_wrist_left")
        self.assertEqual(websocket.messages[3][1:], b"camera_wrist_right")


if __name__ == "__main__":
    unittest.main()
