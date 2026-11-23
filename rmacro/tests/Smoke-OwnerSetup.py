"""Drive the Windows BAT interactively, sending answers only after each prompt."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import threading
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True)
    parser.add_argument("--loader", required=True)
    args = parser.parse_args()
    stage = Path(args.stage)
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    command = [os.environ.get("ComSpec", "cmd.exe"), "/d", "/c", str(stage / "RUN-PYTHON.bat"), "internet-setup"]
    process = subprocess.Popen(command, cwd=str(stage), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, env=environment, bufsize=0)
    output = bytearray()
    ip_prompt, path_prompt = threading.Event(), threading.Event()
    first = "Публичный IPv4 сервера (без порта): ".encode("utf-8")
    second = "Путь к распакованному EternalCore.exe нового клиентского архива: ".encode("utf-8")

    def collect():
        while True:
            data = process.stdout.read(1)
            if not data:
                return
            output.extend(data)
            if output.endswith(first):
                ip_prompt.set()
            if output.endswith(second):
                path_prompt.set()

    reader = threading.Thread(target=collect, daemon=True)
    reader.start()

    def await_prompt(event, label):
        deadline = time.monotonic() + 30
        while not event.wait(0.1):
            if process.poll() is not None:
                raise RuntimeError("Setup exited before the %s prompt." % label)
            if time.monotonic() >= deadline:
                raise RuntimeError("Timed out waiting for the %s prompt." % label)

    try:
        await_prompt(ip_prompt, "IPv4")
        process.stdin.write(b"8.8.8.8\r\n")
        process.stdin.flush()
        await_prompt(path_prompt, "loader")
        process.stdin.write(args.loader.encode("utf-8") + b"\r\n")
        process.stdin.flush()
        process.stdin.close()
        code = process.wait(timeout=60)
        reader.join(timeout=5)
        if code:
            raise RuntimeError("Owner setup returned %s." % code)
        print("PASS: BAT owner setup accepted interactive answers and configured the loader.")
    except Exception:
        if process.poll() is None:
            process.kill()
            process.wait()
        reader.join(timeout=5)
        print(output.decode("utf-8", errors="replace"), file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
