"""Train a separate candidate on explicitly reviewed local frames only."""
import argparse
import datetime
import json
import shutil
from pathlib import Path


def prepare(folder, output):
    from PIL import Image
    data = json.loads((folder / 'annotations.json').read_text(encoding='utf-8'))
    samples = sorted((folder / name, item) for name, item in data.items()
                     if item.get('reviewed') and Path(name).name == name and (folder / name).is_file())
    if len(samples) < 30:
        raise ValueError('Нужно минимум 30 проверенных кадров; рекомендуется несколько сотен.')
    # Temporal holdout and gap reduce leakage from shot bursts. Still not an independent game session.
    cut = int(len(samples) * .75)
    groups = {'train': samples[:cut], 'val': samples[cut+3:]}
    if not any(b[0] == 0 for _, item in groups['train'] for b in item['boxes']):
        raise ValueError('В обучающей части нет размеченных других игроков (класс 0).')
    for split, items in groups.items():
        (output / 'images' / split).mkdir(parents=True)
        (output / 'labels' / split).mkdir(parents=True)
        for image, item in items:
            with Image.open(image) as im:
                w, h = im.size
            lines = []
            for cls, x1, y1, x2, y2 in item['boxes']:
                if cls not in (0, 1) or not (0 <= x1 < x2 <= w and 0 <= y1 < y2 <= h):
                    raise ValueError(f'Некорректный бокс: {image.name}')
                lines.append(f'{cls} {(x1+x2)/2/w} {(y1+y2)/2/h} {(x2-x1)/w} {(y2-y1)/h}')
            shutil.copy2(image, output / 'images' / split / image.name)
            (output / 'labels' / split / (image.stem + '.txt')).write_text('\n'.join(lines), encoding='utf-8')
    config = output / 'data.yaml'
    config.write_text('path: ' + json.dumps(str(output.resolve())) + '\ntrain: images/train\nval: images/val\nnames:\n  0: player\n  1: self\n', encoding='utf-8')
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session', type=Path)
    parser.add_argument('--epochs', type=int, default=20)
    parser.add_argument('--device', default='cpu', choices=['cpu', '0'])
    args = parser.parse_args()
    if not 1 <= args.epochs <= 500:
        parser.error('epochs must be 1..500')
    output = Path.cwd() / 'Assist_training' / datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    config = prepare(args.session, output / 'dataset')
    from ultralytics import YOLO
    model = YOLO('yolo11n.pt')  # download initial general-purpose weights, not game-trained
    model.train(data=str(config), epochs=args.epochs, imgsz=640, batch=4,
                device=args.device, workers=0, project=str(output.resolve()), name='candidate', seed=42)
    print('Candidate weights:', output / 'candidate' / 'weights' / 'best.pt')
    print('Not activated automatically. Validate on another game session before use.')


if __name__ == '__main__':
    main()
