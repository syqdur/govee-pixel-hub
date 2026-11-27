"""Learn and replay H6630 DIY selections from the user's running Govee Desktop.

No firmware changes. Login is performed in Govee Desktop by the user. The bridge
captures only the observed H6630 iot-control request. Session data is protected
with user-scoped Windows DPAPI; it is never printed or sent to another host.
"""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import threading
import urllib.error
import urllib.request

ENDPOINT = "https://app2.govee.com/bff-app/v1/pc/iot-control"
STATE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "GoveeDiyBridge" / "session.dpapi"

HOOK = r'''
const seen = new Set();
for (const mod of Process.enumerateModules().filter(m => /sspicli|secur32/i.test(m.name))) {
  const ptr = mod.findExportByName('EncryptMessage');
  if (!ptr || seen.has(ptr.toString())) continue;
  seen.add(ptr.toString());
  Interceptor.attach(ptr, {onEnter(args) {
    try {
      const desc = args[2], count = desc.add(4).readU32(), buffers = desc.add(8).readPointer();
      if (count > 16) return;
      for (let i = 0; i < count; i++) {
        const buf = buffers.add(i * (8 + Process.pointerSize));
        const size = buf.readU32(), kind = buf.add(4).readU32() & 0x0fffffff;
        if (kind !== 1 || size < 50 || size > 65536) continue;
        const text = buf.add(8).readPointer().readUtf8String(size);
        if (!text.startsWith('POST /bff-app/v1/pc/iot-control HTTP/1.1\r\n')) continue;
        const split = text.indexOf('\r\n\r\n');
        if (split < 0) continue;
        const headers = {};
        for (const line of text.slice(0, split).split('\r\n').slice(1)) {
          const colon = line.indexOf(':');
          if (colon > 0) headers[line.slice(0, colon).toLowerCase()] = line.slice(colon + 1).trim();
        }
        if (headers.host !== 'app2.govee.com' || !headers.authorization) continue;
        const body = JSON.parse(text.slice(split + 4));
        if (body.sku !== 'H6630' || !Number.isInteger(body.id) || body.type !== 0) continue;
        send({kind: 'learned', headers: {
          Authorization: headers.authorization,
          clientid: headers.clientid,
          clientType: headers.clienttype,
          pcversion: headers.pcversion,
          'Accept-Language': headers['accept-language'] || 'en'
        }, body: body});
      }
    } catch (_) { /* Ignore non-HTTP/binary buffers; do not log process memory. */ }
  }});
}
send({kind: 'ready', hooks: seen.size});
'''


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def crypt(data, decrypt=False):
    if sys.platform != "win32":
        raise RuntimeError("This bridge uses Windows user-scoped DPAPI")
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, target = Blob(len(data), buffer), Blob()
    api = ctypes.WinDLL("crypt32", use_last_error=True)
    fn = api.CryptUnprotectData if decrypt else api.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    # CRYPTPROTECT_UI_FORBIDDEN. No machine-wide flag: only this Windows user can decrypt.
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ctypes.WinError(ctypes.get_last_error())
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


def read_state():
    return json.loads(crypt(STATE.read_bytes(), decrypt=True)) if STATE.exists() else {"diys": {}}


def save_state(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    pending = STATE.with_suffix(".tmp")
    pending.write_bytes(crypt(json.dumps(state).encode()))
    pending.replace(STATE)


def learn(args):
    import frida
    device = frida.get_local_device()
    processes = [p for p in device.enumerate_processes() if p.name.lower() == "goveedesktop.exe"]
    if args.pid is not None:
        processes = [p for p in processes if p.pid == args.pid]
    if len(processes) != 1:
        raise RuntimeError("Open exactly one Govee Desktop instance, or specify its --pid")
    done, result = threading.Event(), {}

    def message(event, data):
        if event.get("type") != "send":
            return
        payload = event.get("payload", {})
        if payload.get("kind") == "ready":
            if not payload.get("hooks"):
                result["error"] = "Windows TLS hook not found"
                done.set()
            else:
                print(f"READY: Click the DIY for label {args.name!r} in Govee Desktop.", flush=True)
        elif payload.get("kind") == "learned" and not done.is_set():
            result.update(payload)
            done.set()

    session = device.attach(processes[0].pid)
    try:
        script = session.create_script(HOOK)
        script.on("message", message)
        script.load()
        if not done.wait(args.timeout):
            raise RuntimeError("No matching DIY click captured before timeout")
        if "error" in result:
            raise RuntimeError(result["error"])
        state = read_state()
        state["headers"] = result["headers"]
        state["diys"][args.name] = result["body"]
        save_state(state)
        print(f"Learned {args.name!r}, DIY id {result['body']['id']}. Session saved with DPAPI.")
    finally:
        session.detach()


def apply(name):
    state = read_state()
    if name not in state["diys"]:
        raise RuntimeError("Unknown DIY label; learn it first")
    body = state["diys"][name]
    if body.get("sku") != "H6630" or body.get("type") != 0:
        raise RuntimeError("Refusing an unsupported stored request")
    headers = {k: v for k, v in state["headers"].items() if v is not None}
    headers.update({"Content-Type": "application/json; charset=utf-8", "Accept": "application/json"})
    request = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
            status = payload.get("status", payload.get("code"))
            print(f"HTTP {response.status}; server status: {status}; DIY: {name}")
            if status is not None and str(status) != "200":
                raise RuntimeError("Server did not confirm success; no automatic retry")
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"HTTP {error.code}; if the session expired, learn a DIY again") from None
    print("Request accepted. Verify the actual image on the display.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    commands = ap.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("learn")
    capture.add_argument("name")
    capture.add_argument("--pid", type=int)
    capture.add_argument("--timeout", type=int, default=60)
    replay = commands.add_parser("apply")
    replay.add_argument("name")
    commands.add_parser("list")
    args = ap.parse_args()
    try:
        if args.command == "learn":
            learn(args)
        elif args.command == "apply":
            apply(args.name)
        else:
            for name, body in read_state()["diys"].items():
                print(f"{name}: DIY {body['id']} ({body['sku']})")
    except Exception as error:
        print(f"Error: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
