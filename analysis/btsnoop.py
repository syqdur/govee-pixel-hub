"""Nur-Lese-Analyse eines Android btsnoop-HCI-Mitschnitts (btsnoop_hci.log).

Zweck: das native H6630-Pixelprotokoll aus einem echten App-Mitschnitt belegen, OHNE etwas ans Geraet zu
senden. Der Nutzer zeichnet in den Android-Entwickleroptionen "Bluetooth-HCI-Snoop-Log" auf, malt/laedt im
Govee-Home etwas aufs Display und exportiert das Log. Dieses Werkzeug extrahiert alle ATT-Writes/Notifications,
erkennt Govee-Frames (0x33/0xAA/0xAC/0xEE und die Multi-Paket-Uploads 0xA3/0xA4) und setzt die Upload-Bursts
zu ihrem `value` (dem eigentlichen Pixel-/DIY-Datenstrom) zusammen.

Format: btsnoop v1, Datalink 1002 (HCI UART/H4). Es wird nur gelesen; keine Ausfuehrung, kein Schreibzugriff.
"""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from govee_lab.frames import decode, xor

ATT_CID = 0x0004
# ATT-Opcodes mit (Name, Byte-Offset des Handles, hat-Wert)
ATT_WRITE_OPS = {0x12: "write_req", 0x52: "write_cmd"}
ATT_NOTIFY_OPS = {0x1B: "notify", 0x1D: "indicate"}
GOVEE_FIRST = {0x33, 0xAA, 0xAC, 0xEE, 0xE7, 0xA3, 0xA4}


@dataclass
class AttPdu:
    ts_us: int
    direction: str   # tx (Host->Controller, also Telefon->Geraet) | rx
    handle: int      # ATT-Attribut-Handle
    opcode: int
    op: str
    value: bytes


def _iter_records(raw: bytes):
    if raw[:8] != b"btsnoop\x00":
        raise ValueError("Keine btsnoop-Datei (Signatur fehlt).")
    version, datalink = struct.unpack_from(">II", raw, 8)
    if version != 1:
        raise ValueError(f"btsnoop-Version {version} nicht unterstuetzt (erwartet 1).")
    off = 16
    n = len(raw)
    while off + 24 <= n:
        orig_len, incl_len, flags, _drops, ts = struct.unpack_from(">IIIIq", raw, off)
        off += 24
        data = raw[off:off + incl_len]
        off += incl_len
        if len(data) < incl_len:
            break
        yield flags, ts, data


def pdus_from_acl(records: Any) -> list[AttPdu]:
    """Gemeinsame ATT-Gewinnung fuer btsnoop UND PacketLogger.

    ``records`` liefert ``(ts_us, direction, acl_bytes)``: ``acl_bytes`` beginnt mit dem HCI-ACL-Kopf
    (handle_flags u16le, acl_len u16le), OHNE etwaiges H4-Typ-Byte. L2CAP-Reassembly je Handle+Richtung
    (PB-Flags: 0b10 Start-flushable, 0b00 Start-non-flushable, 0b01 Fortsetzung)."""
    pdus: list[AttPdu] = []
    pending: dict[tuple[int, str], dict[str, Any]] = {}
    for ts, direction, acl in records:
        if len(acl) < 4:
            continue
        hf, acl_len = struct.unpack_from("<HH", acl, 0)
        handle = hf & 0x0FFF
        pb = (hf >> 12) & 0x3
        payload = acl[4:4 + acl_len]
        key = (handle, direction)
        if pb in (0b10, 0b00):  # Start eines L2CAP-PDU
            if len(payload) < 4:
                continue
            l2_len, cid = struct.unpack_from("<HH", payload, 0)
            body = payload[4:]
            if len(body) < l2_len:
                pending[key] = {"cid": cid, "need": l2_len, "buf": bytearray(body)}
                continue
            _emit(pdus, ts, direction, cid, body[:l2_len])
        elif pb == 0b01 and key in pending:  # Fortsetzung
            st = pending[key]
            st["buf"].extend(payload)
            if len(st["buf"]) >= st["need"]:
                _emit(pdus, ts, direction, st["cid"], bytes(st["buf"][:st["need"]]))
                del pending[key]
    return pdus


def _btsnoop_acl_records(path: str | Path):
    raw = Path(path).read_bytes()
    version, datalink = struct.unpack_from(">II", raw, 8)
    for flags, ts, data in _iter_records(raw):
        direction = "rx" if (flags & 0x01) else "tx"
        if datalink == 1002:  # H4: erstes Byte = HCI-Pakettyp
            if not data or data[0] != 0x02:
                continue
            yield ts, direction, data[1:]
        else:  # 1001: reines HCI ACL
            yield ts, direction, data


def parse(path: str | Path) -> list[AttPdu]:
    return pdus_from_acl(_btsnoop_acl_records(path))


def _emit(pdus: list[AttPdu], ts: int, direction: str, cid: int, att: bytes) -> None:
    if cid != ATT_CID or len(att) < 1:
        return
    opcode = att[0]
    if opcode in ATT_WRITE_OPS and len(att) >= 3:
        handle = struct.unpack_from("<H", att, 1)[0]
        pdus.append(AttPdu(ts, direction, handle, opcode, ATT_WRITE_OPS[opcode], att[3:]))
    elif opcode in ATT_NOTIFY_OPS and len(att) >= 3:
        handle = struct.unpack_from("<H", att, 1)[0]
        pdus.append(AttPdu(ts, direction, handle, opcode, ATT_NOTIFY_OPS[opcode], att[3:]))


# ---------------------------------------------------------------- Upload-Reassembly
def reassemble_a3(frames: list[bytes]) -> dict[str, Any] | None:
    """Setzt eine 0xA3-Upload-Sequenz zum value zurueck (Umkehrung von scene_upload_a3)."""
    if not frames or frames[0][0] != 0xA3 or frames[0][1] != 0x00:
        return None
    start = frames[0]
    marker, num_packets, comm = start[2], start[3], start[4]
    value = bytearray(start[5:19])  # START traegt 14 value-Bytes (vor Padding)
    for f in frames[1:]:
        value.extend(f[2:19])
    return {"typ": "A3", "marker": marker, "num_packets": num_packets, "comm_byte": comm,
            "frames": len(frames), "value_hex": bytes(value).hex()}


def reassemble_a4(frames: list[bytes]) -> dict[str, Any] | None:
    """Setzt eine 0xA4-MTU-Upload-Sequenz zusammen (Umkehrung von scene_upload_a4_mtu)."""
    if not frames or frames[0][0] != 0xA4:
        return None
    start = frames[0]
    idx = struct.unpack_from("<H", start, 1)[0]
    if idx != 0:
        return None
    marker, num_packets, comm = start[3], struct.unpack_from("<H", start, 4)[0], start[6]
    # A4-Frames haben exakte Laenge mit BCC-Pruefsumme am Ende (kein Null-Padding): START = a4 idx(2)
    # marker cnt(2) comm value BCC -> value = [7:-1]; MIDDLE/END = a4 idx(2) value BCC -> value = [3:-1].
    value = bytearray(start[7:-1])
    for f in frames[1:]:
        value.extend(f[3:-1])
    return {"typ": "A4", "marker": marker, "num_packets": num_packets, "comm_byte": comm,
            "frames": len(frames), "value_hex": bytes(value).hex()}


def analyze(path: str | Path, log: Any | None = None, out_path: str | Path | None = None) -> dict[str, Any]:
    """btsnoop-Datei analysieren (HCI). Fuer PacketLogger siehe analysis.pklg, das analyze_pdus wiederverwendet."""
    out = Path(out_path) if out_path else Path(path).with_suffix(".govee-funde.json")
    return analyze_pdus(parse(path), str(path), log, out, surface="btsnoop")


def analyze_pdus(pdus: list[AttPdu], source: str, log: Any | None, out_path: Path,
                 surface: str = "capture") -> dict[str, Any]:
    # nur Writes/Notifications, deren Wert wie ein Govee-Frame aussieht
    govee = [p for p in pdus if p.value and p.value[0] in GOVEE_FIRST]
    handles = {}
    for p in govee:
        handles.setdefault((p.handle, p.op), 0)
        handles[(p.handle, p.op)] += 1

    scalars: list[dict[str, Any]] = []
    uploads: list[dict[str, Any]] = []
    cur_a3: list[bytes] = []
    cur_a4: list[bytes] = []

    def flush() -> None:
        if cur_a3:
            r = reassemble_a3(cur_a3)
            if r:
                uploads.append(r)
            cur_a3.clear()
        if cur_a4:
            r = reassemble_a4(cur_a4)
            if r:
                uploads.append(r)
            cur_a4.clear()

    for p in govee:
        v = p.value
        if v[0] == 0xA3:
            if v[1] == 0x00:
                flush()
            cur_a3.append(v)
            if v[1] == 0xFF:
                flush()
            continue
        if v[0] == 0xA4:
            idx = struct.unpack_from("<H", v, 1)[0] if len(v) >= 3 else 0
            if idx == 0:
                flush()
            cur_a4.append(v)
            if idx == 0xFFFF:
                flush()
            continue
        flush()
        if len(v) == 20 and xor(v[:19]) == v[19]:
            d = decode(v, p.direction)
            scalars.append({"ts_us": p.ts_us, "dir": p.direction, "handle": p.handle,
                            "hex": v.hex(), "decoded": d.label, "fields": d.fields})
        else:
            scalars.append({"ts_us": p.ts_us, "dir": p.direction, "handle": p.handle,
                            "hex": v.hex(), "decoded": "roh"})
    flush()

    report = {
        "quelle": source,
        "mitschnitt_typ": surface,
        "att_pakete_gesamt": len(pdus),
        "govee_frames": len(govee),
        "handles": {f"handle_0x{h:04x}/{op}": n for (h, op), n in handles.items()},
        "skalare_frames": scalars,
        "upload_bursts": uploads,
        "hinweis": "Nur aus dem Mitschnitt gelesen. Die value-Bytes der Upload-Bursts sind der rohe "
                   "Pixel-/DIY-Datenstrom des H6630 und muessen noch gedeutet werden (Format, Palette, Layer).",
    }
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if log is not None:
        log.info("analysis", f"{surface}: {len(pdus)} ATT-Pakete, {len(govee)} Govee-Frames, "
                             f"{len(uploads)} Upload-Burst(s).")
        for u in uploads:
            log.add("analysis", "result", f"Upload {u['typ']}: comm=0x{u['comm_byte']:02x}, "
                    f"{u['num_packets']} Pakete, value {len(u['value_hex']) // 2} Byte", **u)
        log.info("analysis", f"Funde gespeichert: {out_path}")
    return report
