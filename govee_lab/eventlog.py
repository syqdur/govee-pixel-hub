"""Zentrales Ereignisprotokoll: jedes gesendete/empfangene Paket und jede Diagnosemeldung mit Zeitstempel.

Eintraege landen als JSON-Zeilen in %LOCALAPPDATA%\\GoveeLab\\logs und werden an GUI-Listener verteilt.
Alles wird vor dem Schreiben durch redact() geschickt.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .redact import redact


def data_dir() -> Path:
    base = os.environ.get("GOVEE_LAB_HOME") or os.path.join(
        os.environ.get("LOCALAPPDATA", str(Path.home())), "GoveeLab")
    path = Path(base)
    path.mkdir(parents=True, exist_ok=True)
    return path


# Ergebnisstufen: ein gesendetes Paket ist KEIN Erfolg.
SENT = "gesendet"            # Bytes hat Windows angenommen
ACKED = "quittiert"          # Geraet hat geantwortet / quittiert
NO_REPLY = "keine Antwort"
REJECTED = "abgelehnt"
VISIBLE = "sichtbar bestaetigt"  # nur durch Nutzerbeobachtung


@dataclass
class Event:
    channel: str            # ble | gatt | lan | cloud | app | analysis
    kind: str               # tx | rx | info | warn | error | result
    summary: str
    hex: str | None = None  # Klartext-Frame (falls entschluesselt) oder Rohdaten
    wire: str | None = None  # Bytes auf der Luft (ggf. verschluesselt)
    fields: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    @property
    def time_str(self) -> str:
        return datetime.fromtimestamp(self.ts).strftime("%H:%M:%S.%f")[:-3]


class EventLog:
    def __init__(self, path: Path | None = None) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.path = path or (data_dir() / "logs" / f"session-{stamp}.jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._listeners: list[Callable[[Event], None]] = []
        self.events: list[Event] = []

    def subscribe(self, fn: Callable[[Event], None]) -> None:
        self._listeners.append(fn)

    def add(self, channel: str, kind: str, summary: str, *, hex: str | None = None,
            wire: str | None = None, **fields: Any) -> Event:
        ev = Event(channel, kind, redact(summary), hex, wire, redact(fields))
        with self._lock:
            self.events.append(ev)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(ev), ensure_ascii=False, default=str) + "\n")
        for fn in list(self._listeners):
            try:
                fn(ev)
            except Exception:  # noqa: BLE001 - ein defekter Listener darf das Protokoll nicht stoppen
                pass
        return ev

    def info(self, channel: str, summary: str, **fields: Any) -> Event:
        return self.add(channel, "info", summary, **fields)

    def warn(self, channel: str, summary: str, **fields: Any) -> Event:
        return self.add(channel, "warn", summary, **fields)

    def error(self, channel: str, summary: str, **fields: Any) -> Event:
        return self.add(channel, "error", summary, **fields)


def console_printer(ev: Event) -> None:
    extra = f"  [{ev.hex}]" if ev.hex else ""
    if ev.wire and ev.wire != ev.hex:
        extra += f"  wire={ev.wire}"
    fields = {k: v for k, v in ev.fields.items() if k not in ("raw",)}
    tail = f"  {fields}" if fields else ""
    print(f"{ev.time_str} {ev.channel:<5} {ev.kind:<6} {ev.summary}{extra}{tail}", flush=True)
