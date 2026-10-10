import pathlib
import unittest

import numpy as np
from dora_openarm_stereo_camera.main import split_stereo_frame
from dora_openarm_stereo_camera.wrist import video_index


class StereoFrameTest(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((2, 6, 3), dtype=np.uint8)
        self.frame[:, :3] = 11
        self.frame[:, 3:] = 22

    def test_split_left_right(self):
        left, right = split_stereo_frame(self.frame, "left-right")

        self.assertEqual(left.shape, (2, 3, 3))
        self.assertEqual(right.shape, (2, 3, 3))
        self.assertTrue(np.all(left == 11))
        self.assertTrue(np.all(right == 22))

    def test_split_right_left_swaps_eyes(self):
        left, right = split_stereo_frame(self.frame, "right-left")

        self.assertTrue(np.all(left == 22))
        self.assertTrue(np.all(right == 11))

    def test_split_rejects_odd_width(self):
        with self.assertRaisesRegex(ValueError, "width must be even"):
            split_stereo_frame(np.zeros((2, 5, 3), dtype=np.uint8), "left-right")


class WristCameraTest(unittest.TestCase):
    def test_video_index_accepts_v4l2_device(self):
        self.assertEqual(video_index(pathlib.Path("/dev/video17")), 17)

    def test_video_index_rejects_non_device_path(self):
        with self.assertRaisesRegex(RuntimeError, "does not resolve"):
            video_index(pathlib.Path("/tmp/camera17"))


if __name__ == "__main__":
    unittest.main()
