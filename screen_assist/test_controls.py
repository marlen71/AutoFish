import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from .settings import DEFAULTS, validate, save, load, cli
from .app import arguments
from .trigger import Trigger, candidate_under_crosshair, activation_allowed
from .tracking import Tracker
from .core import Box


class DeviceTests(unittest.TestCase):
    def test_cuda_unavailable_does_not_force_gpu(self):
        from .detector import resolve_device
        self.assertEqual(resolve_device('0', False), ('cpu', True))
        self.assertEqual(resolve_device('auto', False), ('cpu', False))
        self.assertEqual(resolve_device('cpu', True), ('cpu', False))
        self.assertEqual(resolve_device('auto', True), ('0', False))
        self.assertEqual(resolve_device('0', True), ('0', False))


class SettingsTests(unittest.TestCase):
    def test_cli_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp)/'model.pt'
            model.touch()
            settings = dict(DEFAULTS, model=str(model), aim_activation='auto', trigger_enabled=True)
            with patch('sys.argv',['Assist.py',*cli(settings)]):
                args = arguments()
            self.assertEqual(vars(args),settings)

    def test_defaults_and_save(self):
        self.assertFalse(DEFAULTS['trigger_enabled'])
        self.assertEqual(DEFAULTS['aim_activation'],'rmb')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'settings.json'
            save(DEFAULTS,path)
            self.assertEqual(load(path),DEFAULTS)

    def test_reject_invalid_values(self):
        for key,value in [('confidence',float('nan')),('aim_age',1),('trigger_radius',0),
                          ('monitor',1.5),('classes','-1'),('imgsz',100),('trigger_enabled','false')]:
            with self.subTest(key=key), self.assertRaises((ValueError,TypeError)):
                validate(dict(DEFAULTS,**{key:value}))
        with self.assertRaises(ValueError):
            validate(dict(DEFAULTS,track_confidence=.8,confidence=.2))


class TriggerTests(unittest.TestCase):
    def test_activation_requires_master_focus_and_closed_menu(self):
        self.assertTrue(activation_allowed(True,False,True,'auto',False))
        self.assertTrue(activation_allowed(True,False,True,'rmb',True))
        self.assertFalse(activation_allowed(True,False,True,'rmb',False))
        for mode in ('auto','rmb'):
            self.assertFalse(activation_allowed(False,False,True,mode,True))
            self.assertFalse(activation_allowed(True,True,True,mode,True))
            self.assertFalse(activation_allowed(True,False,False,mode,True))

    def test_disabled_never_clicks(self):
        trigger = Trigger()
        for now in (1., 2., 10.):
            self.assertIsNone(trigger.step(now,1,False))
        self.assertFalse(trigger.pressed)

    def test_dwell_click_release_cooldown(self):
        trigger = Trigger()
        self.assertIsNone(trigger.step(1.,1,True))
        self.assertEqual(trigger.step(1.11,1,True),'down')
        self.assertIsNone(trigger.step(1.12,1,True))
        self.assertEqual(trigger.step(1.14,1,True),'up')
        self.assertIsNone(trigger.step(1.2,1,True))
        self.assertEqual(trigger.step(1.34,1,True),'down')
        self.assertEqual(trigger.cancel(),'up')
        self.assertIsNone(trigger.cancel())

    def test_loss_focus_or_target_releases_immediately(self):
        for allowed,candidate in [(False,1),(True,None),(True,2)]:
            trigger = Trigger()
            trigger.step(1,1,True)
            trigger.step(1.11,1,True)
            self.assertEqual(trigger.step(1.115,candidate,allowed),'up')

    def test_manual_click_and_switch_reset_dwell(self):
        trigger = Trigger()
        trigger.step(1,1,True)
        self.assertIsNone(trigger.step(1.2,1,True,manual_left=True))
        self.assertIsNone(trigger.step(1.3,2,True))
        self.assertIsNone(trigger.step(1.35,2,True))
        self.assertEqual(trigger.step(1.41,2,True),'down')

    def test_requires_fresh_confirmed_point_inside_box(self):
        tracker = Tracker()
        tracker.update([Box(0,0,100,200)],1.)
        tracks = tracker.visible(1.01)
        self.assertIsNotNone(candidate_under_crosshair(tracks,(50,26),'head',1.01,1.,6))
        self.assertIsNone(candidate_under_crosshair(tracks,(50,26),'head',1.01,1.01,6))
        self.assertIsNone(candidate_under_crosshair(tracks,(50,26),'head',1.2,1.,6))
        self.assertIsNone(candidate_under_crosshair(tracks,(90,26),'head',1.01,1.,6))
        tracks[0].box = Box(0,0,100,200,.12)
        self.assertIsNone(candidate_under_crosshair(tracks,(50,26),'head',1.01,1.,6,min_conf=.22))
