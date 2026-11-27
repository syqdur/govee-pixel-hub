"""Entfernt Zugangsdaten, Schluessel und Tokens aus Texten und Strukturen, bevor sie geloggt oder exportiert werden."""
from __future__ import annotations

import re
from typing import Any

SECRET_KEYS = re.compile(
    r"(api[-_]?key|apikey|token|secret|password|passwd|authorization|bearer|session[-_]?key|psk|"
    r"cookie|account[-_]?topic|iot[-_]?key|cert|private)",
    re.IGNORECASE,
)
_INLINE = [
    # Header- oder JSON-artige "Key: Wert"-Paare
    (re.compile(r'(?i)("?(?:govee-api-key|api[-_]?key|authorization|token|secret|password)"?\s*[:=]\s*"?)([^",\s}]+)'),
     r"\1***"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"), r"\1***"),
]
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE)


def _uuid_repl(m: re.Match[str]) -> str:
    """UUID-foermige API-Keys (Govee-Developer-Keys sind UUIDs) ausblenden, GATT-UUIDs behalten."""
    u = m.group(0).lower()
    if u.startswith("00010203-0405-0607-0809-") or u.endswith("-0000-1000-8000-00805f9b34fb"):
        return m.group(0)
    return "<uuid-redacted>"
_MAC = re.compile(r"\b([0-9A-Fa-f]{2})[:-]([0-9A-Fa-f]{2})[:-]([0-9A-Fa-f]{2})[:-]([0-9A-Fa-f]{2})[:-]"
                  r"([0-9A-Fa-f]{2})[:-]([0-9A-Fa-f]{2})\b")


def redact_text(text: str, *, mask_mac: bool = False) -> str:
    for pattern, repl in _INLINE:
        text = pattern.sub(repl, text)
    text = _UUID.sub(_uuid_repl, text)
    if mask_mac:
        text = _MAC.sub(lambda m: f"{m.group(1)}:{m.group(2)}:{m.group(3)}:XX:XX:{m.group(6)}", text)
    return text


def redact(obj: Any, *, mask_mac: bool = False) -> Any:
    """Rekursiv: Werte unter verdaechtigen Schluesseln werden ersetzt, Strings bereinigt."""
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            if isinstance(key, str) and SECRET_KEYS.search(key) and value not in (None, "", False):
                out[key] = "***"
            else:
                out[key] = redact(value, mask_mac=mask_mac)
        return out
    if isinstance(obj, (list, tuple)):
        return [redact(v, mask_mac=mask_mac) for v in obj]
    if isinstance(obj, str):
        return redact_text(obj, mask_mac=mask_mac)
    return obj
