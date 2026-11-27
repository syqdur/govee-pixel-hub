"""Zerlegung von Govee-BLE-Frames (20 Byte Klartext: proType, command, payload, XOR-Pruefsumme).

Die Feldnamen stammen aus govee-ble-local (aus der Govee-App abgeleitet). Fuer den H6630 ist nur ein
Teil davon am Geraet bestaetigt; siehe BERICHT.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PRO_TYPES = {
    0x33: "write",
    0xAA: "read",
    0xA3: "upload(a3)",
    0xA4: "upload(a4)",
    0xAC: "status-burst",
    0xEE: "push",
    0xE7: "handshake",
}

# Kommandos, deren Bedeutung aus der Bibliothek/App-Spur bekannt ist (nicht automatisch fuer H6630 bestaetigt).
COMMANDS = {
    0x01: "power",
    0x04: "brightness",
    0x05: "mode/colour",
    0x06: "soft_version",
    0x07: "device_info",
    0x09: "sync_time",
    0x14: "wifi_mac",
    0x20: "wifi_hard_version",
    0x21: "wifi_soft_version",
    0xB2: "secret",
}
DEVICE_INFO_SELECTORS = {0x02: "sn/device_id", 0x03: "hard_version", 0x10: "basic", 0x11: "wifi"}
ASCII_REPLIES = {0x06, 0x20, 0x21}


def xor(data: bytes) -> int:
    x = 0
    for b in data:
        x ^= b
    return x


def make_frame(pro_type: int, command: int, payload: bytes = b"") -> bytes:
    if len(payload) > 17:
        raise ValueError("payload hoechstens 17 Byte")
    body = bytes([pro_type, command]) + payload.ljust(17, b"\x00")
    return body + bytes([xor(body)])


@dataclass
class Decoded:
    ok_checksum: bool
    pro_type: str
    command: str
    label: str
    fields: dict[str, Any] = field(default_factory=dict)

    def text(self) -> str:
        parts = [self.label]
        if not self.ok_checksum:
            parts.append("PRUEFSUMME FALSCH (verschluesselt oder defekt)")
        parts += [f"{k}={v}" for k, v in self.fields.items()]
        return "  ".join(parts)


def _ascii(payload: bytes) -> str:
    return payload.split(b"\x00", 1)[0].decode("ascii", "replace")


def decode(frame: bytes, direction: str = "?") -> Decoded:
    if len(frame) != 20:
        return Decoded(False, "?", "?", f"len={len(frame)}", {"hinweis": "kein 20-Byte-Frame"})
    ok = xor(frame[:19]) == frame[19]
    pt, cmd, payload = frame[0], frame[1], frame[2:19]
    pt_name = PRO_TYPES.get(pt, f"0x{pt:02x}")
    cmd_name = COMMANDS.get(cmd, f"0x{cmd:02x}")
    fields: dict[str, Any] = {}
    if ok:
        if pt == 0x33 and direction == "rx":
            fields["status"] = "ok" if payload[0] == 0 else f"abgelehnt(0x{payload[0]:02x})"
        elif pt == 0x33 and cmd == 0x01:
            fields["on"] = bool(payload[0])
        elif pt == 0x33 and cmd == 0x04:
            fields["percent"] = payload[0]
        elif pt == 0xAA and direction == "rx":
            if cmd in ASCII_REPLIES:
                fields["text"] = _ascii(payload)
            elif cmd == 0x07:
                fields["selector"] = DEVICE_INFO_SELECTORS.get(payload[0], f"0x{payload[0]:02x}")
                fields["text"] = _ascii(payload[1:])
            elif cmd == 0x01:
                fields["on"] = bool(payload[0])
            elif cmd == 0x04:
                fields["level"] = payload[0]
            elif cmd == 0x14:
                fields["mac"] = ":".join(f"{b:02X}" for b in payload[:6])
        elif pt == 0xAA and cmd == 0x07:
            fields["selector"] = DEVICE_INFO_SELECTORS.get(payload[0], f"0x{payload[0]:02x}")
    label = f"{pt_name}/{cmd_name}"
    try:  # die ausfuehrlichere Beschreibung der Bibliothek, falls vorhanden
        from govee_ble_local.wire.describe import describe_frame
        lib_label, issues = describe_frame(frame, direction if direction in ("tx", "rx") else "?")
        if lib_label and lib_label not in ("bad_checksum",):
            label = f"{label} ({lib_label})"
        if issues:
            fields["spec"] = "; ".join(msg for _, msg in issues)[:200]
    except Exception:  # noqa: BLE001 - Beschreibung ist optional
        pass
    return Decoded(ok, pt_name, cmd_name, label, fields)
