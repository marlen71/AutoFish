"""Assist — standalone screen overlay and aim assistance for Windows.

Run: python Assist.py --model C:\\models\\players.pt
See screen_assist/README.md for setup and limitations.
"""
import sys


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    if getattr(sys, 'frozen', False):
        import os
        from pathlib import Path
        os.chdir(Path(sys.executable).resolve().parent)
        logs = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Assist'
        logs.mkdir(parents=True, exist_ok=True)
        log_path = Path(os.environ.get('ASSIST_JOB_LOG', str(logs / 'assist.log')))
        log = open(log_path, 'a', encoding='utf-8', buffering=1)
        sys.stdout = log
        sys.stderr = log
    if len(sys.argv) > 1 and sys.argv[1] == '--export-onnx':
        del sys.argv[1]
        from screen_assist.export_onnx import main
        main()
    elif len(sys.argv) > 1 and sys.argv[1] == '--train':
        del sys.argv[1]
        from screen_assist.train import main
        main()
    elif len(sys.argv) > 1:
        from screen_assist.app import main
        main()
    else:
        from screen_assist.launcher import launch
        launch()
