import json
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
from PIL import Image
from .proposals import ProposalWorker, similar, priority


class ProposalTests(unittest.TestCase):
    def test_similarity_and_priority(self):
        self.assertTrue(similar(bytes([10, 20]), bytes([11, 21])))
        self.assertFalse(similar(bytes([10]), bytes([30])))
        self.assertFalse(similar(b'abc', None))
        self.assertGreater(priority([]), priority([.9]))
        self.assertGreater(priority([.3]), priority([.9]))

    def test_suggestions_not_confirmed(self):
        ready = threading.Event()
        class FakeModel:
            def __init__(self, *args, **kwargs):
                pass
            def predict(self, *args, **kwargs):
                ready.set()
                return [types.SimpleNamespace(boxes=None)]
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            path = folder / 'frame.jpg'
            Image.new('RGB', (30, 30)).save(path)
            with patch.dict('sys.modules', {'ultralytics': types.SimpleNamespace(YOLO=FakeModel),
                                                  'torch': types.SimpleNamespace(set_num_threads=lambda n: None)}):
                worker = ProposalWorker(folder)
                worker.submit(path)
                self.assertTrue(ready.wait(3))
                worker.queue.join()
                worker.stop.set()
                worker.thread.join(3)
            record = json.loads((folder / 'suggestions/frame.json').read_text())
            self.assertFalse(record['reviewed'])
            self.assertEqual(record['boxes'], [])
            self.assertFalse((folder / 'annotations.json').exists())

    def test_model_failure_keeps_capture_separate(self):
        class BrokenModel:
            def __init__(self, *args, **kwargs):
                raise RuntimeError('offline')
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict('sys.modules', {'ultralytics': types.SimpleNamespace(YOLO=BrokenModel),
                                                  'torch': types.SimpleNamespace(set_num_threads=lambda n: None)}):
                worker = ProposalWorker(tmp)
                worker.thread.join(3)
                worker.submit(Path(tmp) / 'frame.jpg')
                self.assertTrue(worker.failed)
                self.assertEqual(worker.pending, 0)
                self.assertEqual(worker.skipped, 1)
