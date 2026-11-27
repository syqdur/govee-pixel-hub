"""Nur-Lese-Analyse eines Apple-PacketLogger-Mitschnitts (.pklg) – der iPhone-Weg.

Aufnahme ohne Zubehoer/Mac:
  1. Apples kostenloses Bluetooth-Logging-Profil aufs iPhone (developer.apple.com/bug-reporting/profiles).
  2. Im Govee-Home ein Bild/Text aufs H6630-Display schicken.
  3. sysdiagnose ausloesen (Lauter+Leiser+Seitentaste kurz), unter Einstellungen -> Datenschutz ->
     Analyse & Verbesserungen -> Analysedaten das sysdiagnose_...-Archiv teilen.
  4. Im Archiv liegt eine .pklg (PacketLogger) – diese Datei hier auswerten.

Das native Govee-Pixelprotokoll wird daraus belegt, OHNE etwas ans Geraet zu senden.

PacketLogger-Format: Folge von Saetzen, big-endian:
  u32 len (= 9 + Nutzlast) | u32 sekunden | u32 mikrosekunden | u8 typ | nutzlast[len-9]
Typ 0x02 = gesendetes ACL (Telefon->Geraet), 0x03 = empfangenes ACL. Die Nutzlast ist das rohe HCI-ACL-Paket.
"""
from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

from analysis.btsnoop import AttPdu, analyze_pdus, pdus_from_acl

PKLG_ACL_SENT = 0x02
PKLG_ACL_RECV = 0x03


def _acl_records(path: str | Path):
    raw = Path(path).read_bytes()
    off, n = 0, len(raw)
    while off + 13 <= n:
        (length,) = struct.unpack_from(">I", raw, off)
        if length < 9 or off + 4 + length > n:
            break
        secs, usecs, typ = struct.unpack_from(">IIB", raw, off + 4)
        payload = raw[off + 13:off + 4 + length]
        off += 4 + length
        if typ in (PKLG_ACL_SENT, PKLG_ACL_RECV):
            direction = "tx" if typ == PKLG_ACL_SENT else "rx"
            yield secs * 1_000_000 + usecs, direction, payload


def parse(path: str | Path) -> list[AttPdu]:
    return pdus_from_acl(_acl_records(path))


def analyze(path: str | Path, log: Any | None = None, out_path: str | Path | None = None) -> dict[str, Any]:
    out = Path(out_path) if out_path else Path(path).with_suffix(".govee-funde.json")
    return analyze_pdus(parse(path), str(path), log, out, surface="pklg")
