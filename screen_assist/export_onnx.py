"""Explicit offline conversion of trusted Ultralytics detection weights."""
import argparse
import shutil
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--size',type=int,default=512,choices=[320,416,512,640,960,1280])
    args=parser.parse_args()
    if args.model.suffix.lower()!='.pt' or not args.model.is_file():
        parser.error('Select existing trusted .pt detection weights')
    if args.output.suffix.lower()!='.onnx':
        parser.error('Output must end with .onnx')
    from ultralytics import YOLO
    # Ultralytics writes the export beside its source; use an isolated work copy
    # so existing exports or the original weights are never overwritten implicitly.
    import tempfile
    with tempfile.TemporaryDirectory(prefix='assist-export-') as folder:
        source=Path(folder)/args.model.name
        shutil.copy2(args.model,source)
        model=YOLO(str(source),task='detect')
        if model.task!='detect':
            raise ValueError('Only detection models supported, not pose/segmentation')
        result=model.export(format='onnx',imgsz=args.size,dynamic=True,simplify=False,
                            opset=17,nms=False,half=False,device='cpu')
        args.output.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(result,args.output)
    print('Export saved:',args.output)


if __name__=='__main__':
    main()
