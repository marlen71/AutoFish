import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
import numpy as np
from .capture import region_for
from .inference import letterbox, decode_yolo, allowed_classes, OnnxBackend
from .settings import DEFAULTS


class PipelineTests(unittest.TestCase):
    def test_capture_regions(self):
        monitor=dict(left=-1920,top=0,width=1920,height=1080)
        self.assertEqual(region_for(monitor),(0,0,1920,1080))
        self.assertEqual(region_for(monitor,'center',960),(480,60,1440,1020))
        self.assertEqual(region_for(monitor,'center',2048),(420,0,1500,1080))

    def test_letterbox_rgb_and_scale(self):
        frame=np.zeros((100,200,3),dtype=np.uint8)
        frame[:]=(10,20,30)
        tensor,transform=letterbox(frame,320,320)
        self.assertEqual(tensor.shape,(1,3,320,320))
        self.assertEqual(transform,(1.6,0,80))
        self.assertAlmostEqual(float(tensor[0,0,100,100]),30/255,places=6)
        self.assertAlmostEqual(float(tensor[0,2,100,100]),10/255,places=6)
        self.assertEqual(tensor.dtype,np.float32)
        half,_=letterbox(frame,320,320,True)
        self.assertEqual(half.dtype,np.float16)

    def test_nms_and_own_class_exclusion(self):
        # Output: cx,cy,w,h,player,self; highest class is chosen before filtering.
        raw=np.array([[[160,160,160,160,.9,.1],
                       [160,160,158,158,.8,.1],
                       [80,160,20,30,.3,.95]]],dtype=np.float32)
        result=decode_yolo(raw.transpose(0,2,1),{0:'player',1:'self'},[0],.2,(1.6,0,80),(100,200,3))
        self.assertEqual(len(result),1)
        self.assertAlmostEqual(result[0].x1,50)
        self.assertAlmostEqual(result[0].y1,0)
        self.assertAlmostEqual(result[0].x2,150)
        self.assertAlmostEqual(result[0].y2,100)
        transposed=decode_yolo(raw,{0:'player',1:'self'},[0],.2,(1.6,0,80),(100,200,3))
        self.assertEqual(result,transposed)

    def test_fp16_large_boxes_do_not_overflow_nms_area(self):
        raw=np.array([[[640,640,1200,1200,.9,.1],[640,640,1190,1190,.8,.1]]],dtype=np.float16)
        result=decode_yolo(raw,{0:'player',1:'self'},[0],.2,(1,0,0),(1280,1280,3))
        self.assertEqual(len(result),1)

    def test_output_must_be_explicit_raw_detection(self):
        with self.assertRaises(ValueError):
            decode_yolo(np.zeros((1,7,100)),{0:'player',1:'self'},[0],.2,(1,0,0),(100,100,3))
        raw=np.zeros((1,6,10),dtype=np.float32)
        self.assertEqual(decode_yolo(raw,{0:'player',1:'self'},[0],.2,(1,0,0),(100,100,3)),[])
        raw[:]=np.nan
        self.assertEqual(decode_yolo(raw,{0:'player',1:'self'},[0],.2,(1,0,0),(100,100,3)),[])

    def test_class_validation(self):
        self.assertEqual(allowed_classes({0:'player',1:'self'},'0,1'),[0])
        with self.assertRaises(ValueError):
            allowed_classes({0:'player',1:'self'},'2')

    def test_actual_onnx_cpu_session_with_synthetic_model(self):
        import onnx
        from onnx import helper,TensorProto,numpy_helper
        # A tiny constant-output fixture: this tests runtime wiring, NOT game accuracy.
        output=np.array([[[16,16,8,8,.9,.1],[8,8,4,4,.1,.95]]],dtype=np.float32).transpose(0,2,1)
        node=helper.make_node('Constant',[],['detections'],value=numpy_helper.from_array(output))
        graph=helper.make_graph([node],'fixture',[helper.make_tensor_value_info('images',TensorProto.FLOAT,[1,3,32,32])],
                                [helper.make_tensor_value_info('detections',TensorProto.FLOAT,[1,6,2])])
        model=helper.make_model(graph,opset_imports=[helper.make_opsetid('',17)])
        model.ir_version=10
        helper.set_model_props(model,{'names':"{0: 'player', 1: 'self'}",'task':'detect'})
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'fixture.onnx'
            onnx.save(model,file)
            args=SimpleNamespace(**dict(DEFAULTS,model=str(file),onnx_provider='cpu'))
            backend=OnnxBackend(args)
            boxes,metrics=backend.predict(np.zeros((32,32,3),dtype=np.uint8))
            self.assertEqual(len(boxes),1)
            self.assertEqual(boxes[0].x1,12)
            self.assertIn('CPUExecutionProvider',backend.name)
            self.assertIn('32x32',backend.warning)
            self.assertGreaterEqual(metrics['infer_ms'],0)

    def test_multimonitor_auto_capture_uses_mss(self):
        import types
        from unittest.mock import patch
        from .capture import ScreenCapture
        class FakeMSS:
            monitors=[{}, {}, {}]
            def grab(self,region):
                return np.zeros((region['height'],region['width'],4),dtype=np.uint8)
            def close(self):
                pass
        def unexpected(**kwargs):
            raise AssertionError('Must not guess DXGI output mapping on multiple monitors')
        args=SimpleNamespace(**dict(DEFAULTS,capture_region='center',crop_size=256))
        with patch.dict('sys.modules',{'mss':types.SimpleNamespace(mss=FakeMSS),
                                       'dxcam':types.SimpleNamespace(create=unexpected)}):
            capture=ScreenCapture(args,dict(left=-640,top=0,width=640,height=480))
            frame,_,origin,_=capture.grab()
            self.assertEqual(capture.name,'MSS')
            self.assertIn('Multiple monitors',capture.warning)
            self.assertEqual(frame.shape,(256,256,3))
            self.assertEqual(origin,(192,112))
            capture.close()

    def test_dxgi_error_falls_back_and_releases_camera(self):
        import types
        from unittest.mock import patch
        from .capture import ScreenCapture
        class FakeMSS:
            monitors=[{},{}]
            def grab(self,region):
                return np.zeros((region['height'],region['width'],4),dtype=np.uint8)
            def close(self):
                pass
        class Camera:
            released=False
            def grab(self):
                raise RuntimeError('display disconnected')
            def release(self):
                self.released=True
        camera=Camera()
        args=SimpleNamespace(**DEFAULTS)
        with patch.dict('sys.modules',{'mss':types.SimpleNamespace(mss=FakeMSS),
                                       'dxcam':types.SimpleNamespace(create=lambda **kwargs:camera)}):
            capture=ScreenCapture(args,dict(left=0,top=0,width=640,height=480))
            frame,_,_,_=capture.grab()
            self.assertEqual(frame.shape,(480,640,3))
            self.assertEqual(capture.name,'MSS')
            self.assertTrue(camera.released)
            self.assertIn('disconnected',capture.warning)
            capture.close()

    def test_dxgi_cached_frame_preserves_source_time(self):
        import types
        from unittest.mock import patch
        from .capture import ScreenCapture
        class FakeMSS:
            monitors=[{},{}]
            def grab(self,region):
                raise AssertionError('Cache is still within its 80ms lifetime')
            def close(self):
                pass
        class Camera:
            calls=0
            def grab(self):
                self.calls+=1
                return np.zeros((480,640,3),dtype=np.uint8) if self.calls==1 else None
            def release(self):
                pass
        camera=Camera()
        with patch.dict('sys.modules',{'mss':types.SimpleNamespace(mss=FakeMSS),
                                       'dxcam':types.SimpleNamespace(create=lambda **kwargs:camera)}):
            capture=ScreenCapture(SimpleNamespace(**DEFAULTS),dict(left=0,top=0,width=640,height=480))
            with patch('screen_assist.capture.time.perf_counter',side_effect=[1.,1.001,1.02,1.021]):
                _,first,_,_=capture.grab()
                _,second,_,_=capture.grab()
            self.assertEqual(first,second)
            self.assertIn('cached',capture.last_backend)
            capture.close()

    def test_worker_maps_roi_and_closes_without_input_dependencies(self):
        import threading,time
        from unittest.mock import patch
        from .detector import Detector
        from .core import Box
        closed=threading.Event()
        class Capture:
            name=last_backend='fixture capture'
            warning=''
            def __init__(self,*args): pass
            def invalidate(self): pass
            def grab(self):
                time.sleep(.002)
                return np.zeros((20,30,3),dtype=np.uint8),time.perf_counter(),(10,20),.5
            def close(self): closed.set()
        class Backend:
            name='fixture backend'
            warning=''
            def predict(self,frame):
                return [Box(1,2,10,15,.9)],dict(pre_ms=1.,infer_ms=2.,post_ms=1.,model_ms=4.)
        with patch('screen_assist.capture.ScreenCapture',Capture),patch('screen_assist.inference.create_backend',return_value=Backend()):
            detector=Detector(SimpleNamespace(**DEFAULTS),dict(width=50,height=60))
            detector.activate(True)
            deadline=time.monotonic()+2
            while detector.read() is None and not detector.error and time.monotonic()<deadline:
                closed.wait(.005)
            result=detector.read()
            detector.stop.set();detector.enabled.set();detector.thread.join(2)
            self.assertIsNone(detector.error)
            self.assertIsNotNone(result)
            self.assertEqual(result[2][0].x1,11)
            self.assertEqual(result[2][0].y1,22)
            self.assertTrue(closed.is_set())
            metrics,_=detector.diagnostics()
            self.assertEqual(metrics['infer_ms'],2.)

    def test_worker_discards_inflight_result_after_deactivation(self):
        import threading,time
        from unittest.mock import patch
        from .detector import Detector
        entered,release=threading.Event(),threading.Event()
        class Capture:
            name=last_backend='fixture'
            warning=''
            def __init__(self,*args): pass
            def invalidate(self): pass
            def grab(self): return np.zeros((20,20,3),dtype=np.uint8),time.perf_counter(),(0,0),0.
            def close(self): pass
        class Backend:
            name='fixture'
            warning=''
            def predict(self,frame):
                entered.set()
                release.wait(2)
                return [],dict(pre_ms=0.,infer_ms=0.,post_ms=0.,model_ms=0.)
        with patch('screen_assist.capture.ScreenCapture',Capture),patch('screen_assist.inference.create_backend',return_value=Backend()):
            detector=Detector(SimpleNamespace(**DEFAULTS),dict(width=20,height=20))
            detector.activate(True)
            try:
                self.assertTrue(entered.wait(2))
                detector.activate(False)
            finally:
                detector.stop.set();release.set();detector.enabled.set();detector.thread.join(2)
            self.assertIsNone(detector.read())
