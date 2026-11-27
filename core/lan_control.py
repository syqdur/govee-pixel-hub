"""Zero-BLE Govee LAN API helper for brightness control (UDP port 4003)."""
import json
import socket
from typing import Optional

DEFAULT_LAN_IP = "192.168.178.115"
LAN_PORT = 4003


def set_lan_brightness(percent: int, ip: str = DEFAULT_LAN_IP, timeout: float = 1.0) -> bool:
    """Sends a Govee LAN API brightness command over UDP (zero Bluetooth traffic)."""
    val = max(1, min(100, int(percent)))
    payload = json.dumps({
        "msg": {
            "cmd": "brightness",
            "data": {"value": val},
        }
    }).encode("utf-8")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.sendto(payload, (ip, LAN_PORT))
        return True
    except Exception:
        return False


def is_night_time(now_hhmm: str, start_hhmm: str = "23:00", end_hhmm: str = "07:00") -> bool:
    """Returns True if `now_hhmm` (HH:MM) falls inside [start_hhmm, end_hhmm), handling midnight wrap."""
    def to_min(s: str) -> Optional[int]:
        try:
            h, m = s.strip().split(":")
            return int(h) * 60 + int(m)
        except Exception:
            return None

    cur = to_min(now_hhmm)
    start = to_min(start_hhmm)
    end = to_min(end_hhmm)
    if cur is None or start is None or end is None:
        return False
    if start <= end:
        return start <= cur < end
    return cur >= start or cur < end
