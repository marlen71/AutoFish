import unittest
from .core import Box, select_target, smooth_step


class GeometryTests(unittest.TestCase):
    def test_modes(self):
        b = Box(0, 0, 100, 200)
        self.assertEqual(b.point('head'), (50, 26))
        self.assertEqual(b.point('body'), (50, 84))

    def test_selection_and_radius(self):
        boxes = [Box(0, 0, 100, 200), Box(200, 0, 300, 200)]
        self.assertIsNone(select_target(boxes, (500, 500), 10, 'head'))
        self.assertEqual(select_target(boxes, (245, 26), 50, 'head'), (250, 26))
        self.assertIsNone(select_target([], (0, 0), 100, 'head'))

    def test_smooth_and_cap(self):
        fast = smooth_step((0, 0), (100, 0), 1, 1/60, 10000)[0]
        slow = smooth_step((0, 0), (100, 0), 20, 1/60, 10000)[0]
        self.assertTrue(0 < slow < fast < 100)
        self.assertAlmostEqual(smooth_step((0, 0), (100, 0), 1, .01, 100)[0], 1)
        self.assertEqual(smooth_step((0, 0), (10, 10), 1, 0, 100), (0, 0))

    def test_frame_rate_independence(self):
        x = 0
        for _ in range(60):
            x += smooth_step((x, 0), (100, 0), 10, 1/60, 10000)[0]
        y = 0
        for _ in range(30):
            y += smooth_step((y, 0), (100, 0), 10, 1/30, 10000)[0]
        self.assertAlmostEqual(x, y)


if __name__ == '__main__':
    unittest.main()
