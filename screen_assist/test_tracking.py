import unittest
from .core import Box
from .tracking import Tracker


class TrackingTests(unittest.TestCase):
    def test_smoothing_and_id(self):
        tracker = Tracker(tau=.055)
        tracker.update([Box(0, 0, 100, 200)], 1.)
        tracker.update([Box(10, 0, 110, 200)], 1.03)
        tracks = tracker.visible(1.03)
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].id, 1)
        self.assertTrue(0 < tracks[0].box.x1 < 10)

    def test_brief_miss_then_expiry(self):
        tracker = Tracker(hold=.3)
        tracker.update([Box(0, 0, 100, 200)], 1.)
        tracker.update([], 1.05)
        self.assertEqual(len(tracker.visible(1.1)), 1)
        self.assertIsNotNone(tracker.choose((50, 26), 100, 'head', 1.1, max_age=.2))
        self.assertIsNone(tracker.choose((50, 26), 100, 'head', 1.25, max_age=.2))
        self.assertEqual(tracker.visible(1.4), [])

    def test_target_lock_does_not_jump_to_nearer(self):
        tracker = Tracker()
        tracker.update([Box(0, 0, 100, 200), Box(100, 0, 200, 200)], 1.)
        chosen = tracker.choose((140, 26), 200, 'head', 1.01, locked=1)
        self.assertEqual(chosen.id, 1)
        self.assertIsNone(tracker.choose((500, 500), 10, 'head', 1.01, locked=1))

    def test_no_matching_distant_box(self):
        tracker = Tracker()
        tracker.update([Box(0, 0, 100, 200)], 1.)
        tracker.update([Box(500, 0, 600, 200)], 1.02)
        self.assertEqual(len(tracker.visible(1.02)), 2)
        self.assertEqual(len(tracker.visible(1.3)), 0)

    def test_default_follows_latest_coordinates_without_filter_delay(self):
        tracker = Tracker()
        tracker.update([Box(0, 0, 100, 200)], 1.)
        tracker.update([Box(30, 0, 130, 200)], 1.02)
        self.assertEqual(tracker.visible(1.02)[0].box.x1, 30)
        self.assertEqual(tracker.visible(1.02)[0].id, 1)

    def test_unmatched_track_is_not_drawn_as_a_trail(self):
        tracker = Tracker(hold=.3)
        tracker.update([Box(0, 0, 100, 200)], 1.)
        tracker.update([Box(500, 0, 600, 200)], 1.05)
        self.assertEqual(len(tracker.visible(1.06)), 2)
        shown = tracker.display(1.06, 1.05)
        self.assertEqual(len(shown), 1)
        self.assertEqual(shown[0].box.x1, 500)
        self.assertEqual(tracker.display(1.26, 1.05), [])

    def test_empty_latest_result_does_not_draw_old_box(self):
        tracker = Tracker(hold=.3)
        tracker.update([Box(0, 0, 100, 200)], 1.)
        tracker.update([], 1.05)
        self.assertEqual(tracker.display(1.06, 1.05), [])
