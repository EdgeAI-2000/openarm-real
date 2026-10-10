"""Verify network image validation and the two independent clock references."""

import base64
import unittest

import cv2
import numpy as np

from dora_openarm_stereo_camera.overhead import decode_frame


class OverheadFrameTests(unittest.TestCase):
    def setUp(self):
        _, image = cv2.imencode(".jpg", np.zeros((12, 16, 3), dtype=np.uint8))
        self.jpeg = image.tobytes()
        self.message = {
            "format": "rgb8; jpeg compressed bgr8",
            "header": {"stamp": {"sec": 100, "nanosec": 123}, "frame_id": "d455_color"},
            "data": base64.b64encode(self.jpeg).decode("ascii"),
        }

    def test_remote_clock_does_not_replace_local_recording_time(self):
        frame = decode_frame(self.message, 500_000_000_456, 42.0)
        self.assertEqual(frame.jpeg, self.jpeg)
        self.assertEqual(frame.source_ns, 100_000_000_123)
        self.assertEqual(frame.received_ns, 500_000_000_456)
        self.assertEqual(frame.received_monotonic, 42.0)

    def test_ros_byte_array_is_accepted(self):
        self.message["data"] = list(self.jpeg)
        self.assertEqual(decode_frame(self.message, 1, 1.0).jpeg, self.jpeg)

    def test_invalid_image_cannot_enter_dataset(self):
        for data in ["not base64!", base64.b64encode(b"\xff\xd8broken").decode("ascii")]:
            with self.subTest(data=data):
                self.message["data"] = data
                with self.assertRaises(ValueError):
                    decode_frame(self.message, 1, 1.0)

    def test_depth_or_png_cannot_be_written_as_jpeg(self):
        self.message["format"] = "png"
        with self.assertRaises(ValueError):
            decode_frame(self.message, 1, 1.0)

    def test_missing_capture_timestamp_is_rejected(self):
        self.message["header"] = {}
        with self.assertRaises(ValueError):
            decode_frame(self.message, 1, 1.0)


if __name__ == "__main__":
    unittest.main()
