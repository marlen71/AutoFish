import math
import unittest
from .aim_control import AimController,safe_point
from .core import Box
from .tracking import Tracker


class AimControlTests(unittest.TestCase):
    def setUp(self):
        self.box=Box(150,0,250,200)
        self.point=safe_point(self.box,'body')

    def step(self,controller,seq,captured,**kwargs):
        args=dict(target_id=1,box=self.box,origin=(100,84),point=self.point,now=captured+.01)
        args.update(kwargs)
        return controller.step(seq,captured,**args)

    def test_needs_distinct_confirmed_frames_and_never_replays(self):
        c=AimController()
        self.assertEqual(self.step(c,1,1.),(0,0))
        dx,dy=self.step(c,2,1.1)
        self.assertGreater(dx,0)
        self.assertEqual(dy,0)
        for _ in range(100):
            self.assertEqual(self.step(c,2,1.1),(0,0))

    def test_step_limit_and_target_switch(self):
        c=AimController()
        self.step(c,1,1.)
        dx,dy=self.step(c,2,1.1,gain=1.,smooth=1.,limit=3.)
        self.assertLessEqual(math.hypot(dx,dy),3.)
        self.assertEqual(self.step(c,3,1.2,target_id=2),(0,0))

    def test_box_resize_outlier_requires_reconfirmation(self):
        c=AimController()
        self.step(c,1,1.)
        self.step(c,2,1.1)
        outlier=Box(0,0,1000,1000)
        self.assertEqual(self.step(c,3,1.2,box=outlier,point=safe_point(outlier,'body')),(0,0))
        self.assertEqual(self.step(c,4,1.3),(0,0))

    def test_deadzone_stale_and_outside_box(self):
        c=AimController()
        self.step(c,1,1.)
        self.assertEqual(self.step(c,2,1.1,origin=self.point),(0,0))
        self.assertEqual(self.step(c,3,1.2,now=1.6),(0,0))
        self.assertEqual(self.step(c,4,1.7,point=(900,900)),(0,0))

    def test_duplicate_source_timestamp_does_not_confirm(self):
        c=AimController()
        self.step(c,1,1.)
        self.assertEqual(self.step(c,2,1.),(0,0))
        self.assertEqual(c.confirmed,1)

    def test_point_is_inside_real_box_and_no_prediction(self):
        self.assertEqual(safe_point(self.box,'head'),(200,26))
        self.assertEqual(safe_point(self.box,'body'),(200,84))
        self.assertTrue(self.box.y1<safe_point(self.box,'head',-10)[1]<self.box.y2)
        self.assertIsNone(safe_point(Box(20,0,10,10),'head'))
        self.assertIsNone(safe_point(Box(float('nan'),0,100,200),'head'))

    def test_coasting_track_cannot_be_selected_for_aim(self):
        tracker=Tracker(hold=.4)
        tracker.update([self.box],1.)
        tracker.update([],1.05)
        self.assertIsNone(tracker.choose((200,26),100,'head',1.06,confirmed_at=1.05))
        self.assertTrue(tracker.render(1.06,1.05))
