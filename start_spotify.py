"""Robust manager and starter for Govee Pixel Hub."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
PID_FILE = ROOT / "spotify-output" / "worker.json"
LOG_FILE = ROOT / "spotify-output" / "worker.log"
PYTHON = ROOT / ".venv-pixel" / "Scripts" / "python.exe"
PYTHONW = ROOT / ".venv-pixel" / "Scripts" / "pythonw.exe"


def get_running_hub_pids():
    """Finds all running processes executing hub.py."""
    pids = []
    try:
        cmd = 'Get-CimInstance Win32_Process -Filter "Name like \'python%\'" | Where-Object { $_.CommandLine -like "*hub.py*" } | Select-Object -ExpandProperty ProcessId'
        res = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            for line in res.stdout.strip().splitlines():
                line = line.strip()
                if line.isdigit():
                    pids.append(int(line))
    except Exception:
        pass
    return pids


def kill_all_hubs():
    """Terminates all running hub.py processes (including venv launcher trees)."""
    pids = set(get_running_hub_pids())
    if PID_FILE.exists():
        try:
            saved_pid = json.loads(PID_FILE.read_text(encoding="utf-8")).get("pid")
            if isinstance(saved_pid, int) and saved_pid > 0:
                pids.add(saved_pid)
        except Exception:
            pass

    for pid in pids:
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=5)
        except Exception:
            pass

    if pids:
        time.sleep(0.5)

    if PID_FILE.exists():
        try:
            PID_FILE.unlink()
        except Exception:
            pass


def is_hub_healthy(port=5000, timeout=1.0):
    """Checks if the hub REST API responds and BLE is not stuck."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=timeout) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("active_plugin") is None:
                    return False
                ble = data.get("ble") or {}
                last_err = str(ble.get("last_error") or "")
                if "GoveeBleTimeout" in last_err and ble.get("total_uploads", 0) == 0:
                    return False
                return True
    except Exception:
        pass
    return False


async def async_turn_off():
    try:
        from pixel_ble import BlePixelClient
        c = BlePixelClient()
        await c.turn_off()
        await c.close()
    except Exception:
        pass


def stop_hub():
    print("Stoppe Govee Pixel Hub...")
    kill_all_hubs()
    try:
        asyncio.run(async_turn_off())
    except Exception:
        pass
    print("[OK] Govee Pixel Hub wurde beendet.")


def start_hub(open_browser=True):
    # Check if already running and healthy
    pids = get_running_hub_pids()
    if pids and is_hub_healthy():
        print(f"[OK] Govee Pixel Hub laeuft bereits (PID {pids[0]}).")
        print("Web-Dashboard: http://127.0.0.1:5000/")
        if open_browser:
            import webbrowser
            webbrowser.open("http://127.0.0.1:5000/")
        return True

    # If old or stuck processes exist, kill them first
    if pids:
        print("Bereinige alte Hub-Prozesse...")
        kill_all_hubs()
        time.sleep(1.0)

    py_exe = PYTHONW if PYTHONW.exists() else PYTHON
    if not py_exe.exists():
        print(f"[FEHLER] Python nicht gefunden in {PYTHON}!")
        print("Bitte zuerst 'Install-PixelHub.bat' ausfuehren.")
        return False

    PID_FILE.parent.mkdir(exist_ok=True)
    env = dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1")

    CREATE_NEW_PROCESS_GROUP = 0x00000200
    CREATE_NO_WINDOW = 0x08000000
    flags = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW

    proc = subprocess.Popen(
        [str(py_exe), str(ROOT / "hub.py")],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    )

    PID_FILE.write_text(json.dumps({"pid": proc.pid, "start_time": time.time()}))

    print("Warte auf Verbindung...", end="", flush=True)
    online = False
    for _ in range(10):
        time.sleep(0.5)
        print(".", end="", flush=True)
        if is_hub_healthy():
            online = True
            break

    print()
    if online:
        print(f"[OK] Govee Pixel Hub erfolgreich gestartet (PID {proc.pid})!")
        print("Web-Dashboard: http://127.0.0.1:5000/")
        if open_browser:
            import webbrowser
            webbrowser.open("http://127.0.0.1:5000/")
        return True
    else:
        if proc.poll() is not None:
            print(f"[FEHLER] Hub-Prozess wurde unerwartet beendet (Code {proc.returncode}).")
            if LOG_FILE.exists():
                lines = LOG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
                print("\nLetzte Log-Meldungen:")
                for l in lines[-8:]:
                    print("  " + l)
        else:
            print("[INFO] Hub laeuft im Hintergrund (Initialisierung laeuft noch).")
            print("Web-Dashboard: http://127.0.0.1:5000/")
            if open_browser:
                import webbrowser
                webbrowser.open("http://127.0.0.1:5000/")
            return True
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stop", action="store_true", help="Stop the running hub")
    parser.add_argument("--restart", action="store_true", help="Restart the hub")
    parser.add_argument("--status", action="store_true", help="Check status of the hub")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser on start")
    parser.add_argument("--delay", type=float, default=0.0, help="Seconds to wait before starting (useful on PC boot)")
    args = parser.parse_args()

    if args.delay > 0:
        time.sleep(args.delay)

    if args.stop:
        stop_hub()
        return

    if args.restart:
        print("Starte Hub neu...")
        stop_hub()
        time.sleep(1.0)
        start_hub(open_browser=not args.no_browser)
        return

    if args.status:
        pids = get_running_hub_pids()
        if pids and is_hub_healthy():
            print(f"Govee Pixel Hub ist AKTIV (PID {pids[0]}).")
            print("Web-Dashboard: http://127.0.0.1:5000/")
        else:
            print("Govee Pixel Hub ist NICHT aktiv.")
        return

    start_hub(open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
