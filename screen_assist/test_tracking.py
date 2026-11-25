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

    def test_low_confidence_continues_but_cannot_create_track(self):
        tracker = Tracker(hold=.4, acquire=.3)
        tracker.update([Box(0,0,100,200,.2)],1.)
        self.assertEqual(tracker.visible(1.),[])
        tracker.update([Box(0,0,100,200,.8)],1.01)
        tracker.update([Box(5,0,105,200,.15)],1.05)
        tracks = tracker.visible(1.05)
        self.assertEqual(len(tracks),1)
        self.assertEqual(tracks[0].id,1)
        self.assertEqual(tracks[0].box.confidence,.15)

    def test_motion_compensation_is_bounded(self):
        tracker = Tracker(hold=.5)
        tracker.update([Box(0,0,100,200)],1.)
        tracker.update([Box(40,0,140,200)],1.02)
        track = tracker.visible(1.02)[0]
        predicted = track.projected(1.12,.06)
        self.assertGreater(predicted.x1,40)
        self.assertLessEqual(predicted.x1,90)
        self.assertEqual(track.projected(1.4,.06),predicted)
        self.assertEqual(track.projected(1.12,0).x1,40)

    def test_coasting_is_marked_and_expires(self):
        tracker = Tracker(hold=.4)
        tracker.update([Box(0,0,100,200)],1.)
        tracker.update([],1.1)
        rendered = tracker.render(1.15,1.1,max_age=.3)
        self.assertTrue(rendered[0][2])
        self.assertEqual(tracker.render(1.35,1.1,max_age=.3),[])
