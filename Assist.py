"""Assist — standalone screen overlay and aim assistance for Windows.

Run: python Assist.py --model C:\\models\\players.pt
See screen_assist/README.md for setup and limitations.
"""
import sys


if __name__ == '__main__':
    if getattr(sys, 'frozen', False):
        import os
        from pathlib import Path
        logs = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Assist'
        logs.mkdir(parents=True, exist_ok=True)
        log = open(logs / 'assist.log', 'a', encoding='utf-8', buffering=1)
        sys.stdout = log
        sys.stderr = log
    if len(sys.argv) > 1:
        from screen_assist.app import main
        main()
    else:
        from screen_assist.launcher import launch
        launch()
