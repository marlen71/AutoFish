import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from .train import prepare


class DatasetTests(unittest.TestCase):
    def test_reviewed_only_and_normalization(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = root / 'session'
            session.mkdir()
            data = {}
            for i in range(40):
                name = f'{i:03}.png'
                Image.new('RGB', (100, 200)).save(session / name)
                data[name] = dict(reviewed=i < 35, boxes=[[0, 10, 20, 90, 180]])
            (session / 'annotations.json').write_text(json.dumps(data))
            config = prepare(session, root / 'dataset')
            self.assertTrue(config.exists())
            train = list((root / 'dataset/images/train').glob('*'))
            val = list((root / 'dataset/images/val').glob('*'))
            self.assertEqual(len(train), 26)
            self.assertEqual(len(val), 6)
            line = (root / 'dataset/labels/train/000.txt').read_text()
            self.assertEqual(line, '0 0.5 0.5 0.8 0.8')
            self.assertFalse({p.name for p in train} & {p.name for p in val})

    def test_too_few(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'annotations.json').write_text('{}')
            with self.assertRaises(ValueError):
                prepare(root, root / 'out')
