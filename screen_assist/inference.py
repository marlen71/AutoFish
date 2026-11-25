"""Independent inference adapters; no mouse input or UI dependencies."""
import ast
import time
from pathlib import Path
from .core import Box


def resolve_device(requested, cuda_available):
    if requested == 'cpu':
        return 'cpu', False
    if cuda_available:
        return '0', False
    return 'cpu', requested == '0'


def allowed_classes(names, requested):
    requested = [int(c) for c in requested.split(',')] if isinstance(requested,str) else requested
    if any(c not in names for c in requested):
        raise ValueError(f'Unknown class IDs {requested}; available: {names}')
    result = [c for c in requested if str(names[c]).lower() not in ('self','own_player')]
    if not result:
        raise ValueError('No target classes remain after excluding self')
    return result


def letterbox(frame, height, width, fp16=False):
    import cv2
    import numpy as np
    fh,fw = frame.shape[:2]
    scale = min(width/fw,height/fh)
    rw,rh = round(fw*scale),round(fh*scale)
    left,top = (width-rw)//2,(height-rh)//2
    image = np.full((height,width,3),114,dtype=np.uint8)
    image[top:top+rh,left:left+rw] = cv2.resize(frame,(rw,rh),interpolation=cv2.INTER_LINEAR)
    tensor = np.ascontiguousarray(image[:,:,::-1].transpose(2,0,1)[None],
                                 dtype=np.float16 if fp16 else np.float32)/255.
    return tensor, (scale,left,top)


def decode_yolo(output, names, classes, confidence, transform, frame_shape, nms_iou=.45):
    """Ultralytics raw YOLOv8/11 [1,4+nc,N] or [1,N,4+nc]. No format guessing."""
    import numpy as np
    data = np.asarray(output,dtype=np.float32)
    channels = 4+len(names)
    if data.ndim != 3 or data.shape[0] != 1:
        raise ValueError(f'Unsupported ONNX output {data.shape}: export raw YOLO detection without NMS')
    data = data[0]
    if data.shape[0] == channels:
        data = data.T
    elif data.shape[1] != channels:
        raise ValueError(f'Unsupported output {data.shape}; expected 4+{len(names)} channels (YOLOv8/11)')
    scores = data[:,4:]
    labels = scores.argmax(axis=1)
    probs = scores[np.arange(len(scores)),labels]
    keep = np.isfinite(data).all(axis=1) & np.isin(labels,classes) & (probs >= confidence)
    coords,probs,labels = data[keep,:4].copy(),probs[keep],labels[keep]
    if not len(coords):
        return []
    # Bound CPU NMS workload on noisy frames.
    order = np.argsort(-probs)[:1000]
    coords,probs,labels = coords[order],probs[order],labels[order]
    scale,left,top = transform
    xy = np.empty_like(coords)
    xy[:,0] = (coords[:,0]-coords[:,2]/2-left)/scale
    xy[:,1] = (coords[:,1]-coords[:,3]/2-top)/scale
    xy[:,2] = (coords[:,0]+coords[:,2]/2-left)/scale
    xy[:,3] = (coords[:,1]+coords[:,3]/2-top)/scale
    fh,fw = frame_shape[:2]
    xy[:,[0,2]] = xy[:,[0,2]].clip(0,fw)
    xy[:,[1,3]] = xy[:,[1,3]].clip(0,fh)
    valid = (xy[:,2]>xy[:,0]) & (xy[:,3]>xy[:,1])
    xy,probs,labels = xy[valid],probs[valid],labels[valid]
    pending = np.arange(len(xy))
    area = (xy[:,2]-xy[:,0])*(xy[:,3]-xy[:,1])
    result = []
    while len(pending) and len(result)<200:
        i = pending[0]
        result.append(Box(*map(float,xy[i]),float(probs[i])))
        rest = pending[1:]
        lt = np.maximum(xy[i,:2],xy[rest,:2])
        rb = np.minimum(xy[i,2:],xy[rest,2:])
        overlap = np.maximum(0,rb-lt).prod(axis=1)
        union = area[i]+area[rest]-overlap
        iou = overlap/np.maximum(union,1e-9)
        pending = rest[(iou<=nms_iou) | (labels[rest]!=labels[i])]
    return result


class TorchBackend:
    def __init__(self,a):
        import numpy as np
        import torch
        from ultralytics import YOLO
        torch.set_num_threads(a.cpu_threads)
        self.model = YOLO(a.model,task='detect')
        self.classes = allowed_classes(self.model.names,a.classes)
        self.conf = min(a.confidence,a.track_confidence)
        self.size = a.imgsz
        self.device,fallback = resolve_device(a.device,torch.cuda.is_available())
        self.model.fuse(verbose=False)
        self.warning = ''
        warmup = np.zeros((a.imgsz,a.imgsz,3),dtype=np.uint8)
        try:
            self.predict(warmup)
        except Exception:
            if self.device == 'cpu':
                raise
            self.device,fallback = 'cpu',True
            self.model.to('cpu')
            self.model.predictor = None
            self.predict(warmup)
        if fallback:
            self.warning = 'GPU unavailable; CPU fallback'
        self.name = f'PyTorch / {self.device}'

    def predict(self,frame):
        started = time.perf_counter()
        result = self.model.predict(frame,classes=self.classes,conf=self.conf,imgsz=self.size,
                                    device=self.device,verbose=False)[0]
        boxes = []
        if result.boxes is not None:
            for xy,conf in zip(result.boxes.xyxy.cpu().tolist(),result.boxes.conf.cpu().tolist()):
                boxes.append(Box(*map(float,xy),float(conf)))
        speed = result.speed or {}
        total = (time.perf_counter()-started)*1000
        return boxes, dict(pre_ms=float(speed.get('preprocess',0)), infer_ms=float(speed.get('inference',0)),
                           post_ms=float(speed.get('postprocess',0)), model_ms=total)


class OnnxBackend:
    def __init__(self,a):
        import numpy as np
        import onnxruntime as ort
        self.warning = ''
        available = ort.get_available_providers()
        options = ort.SessionOptions()
        options.intra_op_num_threads = a.cpu_threads
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.enable_mem_pattern = False  # DirectML requirement
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        choices = {'directml':'DmlExecutionProvider','cuda':'CUDAExecutionProvider','cpu':'CPUExecutionProvider'}
        if a.onnx_provider == 'auto':
            provider = next((p for p in ['DmlExecutionProvider','CUDAExecutionProvider','CPUExecutionProvider'] if p in available),'CPUExecutionProvider')
        else:
            provider = choices[a.onnx_provider]
            if provider not in available:
                self.warning = f'{provider} not installed; CPU fallback'
                provider = 'CPUExecutionProvider'
        providers = [provider] + (['CPUExecutionProvider'] if provider != 'CPUExecutionProvider' else [])
        try:
            self.session = ort.InferenceSession(a.model,sess_options=options,providers=providers)
        except Exception:
            if provider == 'CPUExecutionProvider':
                raise
            self.warning = f'{provider} initialization failed; CPU fallback'
            provider = 'CPUExecutionProvider'
            self.session = ort.InferenceSession(a.model,sess_options=options,providers=[provider])
        inputs = self.session.get_inputs()
        if len(inputs)!=1 or len(inputs[0].shape)!=4 or inputs[0].shape[1] not in (3,'channels'):
            raise ValueError('ONNX requires one NCHW RGB detection input with 3 channels')
        inp = inputs[0]
        if inp.shape[0] not in (1,None,'batch','batch_size') and isinstance(inp.shape[0],int):
            raise ValueError('Only ONNX batch size 1 is supported')
        self.height = inp.shape[2] if isinstance(inp.shape[2],int) else a.imgsz
        self.width = inp.shape[3] if isinstance(inp.shape[3],int) else a.imgsz
        if not (32<=self.height<=4096 and 32<=self.width<=4096):
            raise ValueError('Invalid ONNX input dimensions')
        if inp.type not in ('tensor(float)','tensor(float16)'):
            raise ValueError('Only FP32/FP16 ONNX input supported')
        self.fp16 = inp.type == 'tensor(float16)'
        self.input_name = inp.name
        metadata = self.session.get_modelmeta().custom_metadata_map
        try:
            raw = ast.literal_eval(metadata['names'])
            self.names = {int(k):str(v) for k,v in (enumerate(raw) if isinstance(raw,list) else raw.items())}
            if set(self.names) != set(range(len(self.names))) or not self.names:
                raise ValueError()
        except (KeyError,ValueError,TypeError,SyntaxError,AttributeError):
            raise ValueError('ONNX needs Ultralytics names metadata; use Assist export tool')
        self.classes = allowed_classes(self.names,a.classes)
        self.conf = min(a.confidence,a.track_confidence)
        try:
            self.predict(np.zeros((self.height,self.width,3),dtype=np.uint8))
        except Exception:
            if provider == 'CPUExecutionProvider':
                raise
            self.warning = f'{provider} warmup failed; CPU fallback'
            self.session = ort.InferenceSession(a.model,sess_options=options,providers=['CPUExecutionProvider'])
            self.predict(np.zeros((self.height,self.width,3),dtype=np.uint8))
        self.name = 'ONNX / ' + ','.join(self.session.get_providers())
        if self.height != a.imgsz or self.width != a.imgsz:
            self.warning += f' Fixed model input {self.width}x{self.height} overrides menu size.'

    def predict(self,frame):
        start = time.perf_counter()
        tensor,transform = letterbox(frame,self.height,self.width,self.fp16)
        pre = time.perf_counter()
        output = self.session.run(None,{self.input_name:tensor})
        inferred = time.perf_counter()
        if len(output)!=1:
            raise ValueError('Unsupported ONNX output: export detection model without NMS, not segmentation/pose')
        boxes = decode_yolo(output[0],self.names,self.classes,self.conf,transform,frame.shape)
        end = time.perf_counter()
        return boxes, dict(pre_ms=(pre-start)*1000,infer_ms=(inferred-pre)*1000,
                           post_ms=(end-inferred)*1000,model_ms=(end-start)*1000)


def create_backend(a):
    kind = a.inference_backend
    if kind == 'auto':
        kind = 'onnx' if Path(a.model).suffix.lower()=='.onnx' else 'pytorch'
    try:
        return OnnxBackend(a) if kind == 'onnx' else TorchBackend(a)
    except ImportError as exc:
        hint = 'Run Install_Acceleration.bat for ONNX Runtime.' if kind == 'onnx' else 'Run Start_Assist.bat to install core dependencies.'
        raise RuntimeError(f'{exc}. {hint}') from exc
