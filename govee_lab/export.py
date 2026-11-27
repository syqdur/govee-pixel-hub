"""Exportiert ein bereinigtes Diagnosepaket (ZIP): Protokolle, Funde, Systeminfo – Geheimnisse ausgeblendet."""
from __future__ import annotations

import json
import platform
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from . import __version__
from .eventlog import EventLog, data_dir
from .redact import redact


def _system_info() -> dict[str, Any]:
    return {
        "zeitpunkt": datetime.now().isoformat(timespec="seconds"),
        "govee_lab_version": __version__,
        "python": sys.version,
        "platform": platform.platform(),
    }


def export_bundle(log: EventLog, out_path: Path | None = None, mask_mac: bool = False,
                  extra: dict[str, Any] | None = None) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = out_path or (data_dir() / "exports" / f"govee-diagnose-{stamp}.zip")
    out.parent.mkdir(parents=True, exist_ok=True)

    events = [redact({"ts": e.ts, "time": e.time_str, "channel": e.channel, "kind": e.kind,
                      "summary": e.summary, "hex": e.hex, "wire": e.wire, "fields": e.fields},
                     mask_mac=mask_mac) for e in log.events]
    summary = {
        "system": _system_info(),
        "ereignisse_gesamt": len(events),
        "kanaele": sorted({e["channel"] for e in events}),
        "hinweis": "Automatisch bereinigt: API-Keys/Tokens/Passwoerter ausgeblendet."
                   + (" MAC-Adressen teil-maskiert." if mask_mac else ""),
    }
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("zusammenfassung.json", json.dumps(summary, indent=2, ensure_ascii=False))
        z.writestr("ereignisse.jsonl", "\n".join(json.dumps(e, ensure_ascii=False) for e in events))
        if extra:
            z.writestr("funde.json", json.dumps(redact(extra, mask_mac=mask_mac), indent=2, ensure_ascii=False))
        bericht = Path(__file__).resolve().parent.parent / "BERICHT.md"
        if bericht.exists():
            z.write(bericht, "BERICHT.md")
    log.add("app", "result", f"Diagnosepaket exportiert: {out}")
    return out
