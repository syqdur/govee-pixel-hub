"""Einfache lokale Oberflaeche (Tkinter) fuer Suche, Verbindung, Diagnose, bekannte Befehle, Experimente,
Paketansicht, LAN, Cloud und Export. Keine zusaetzlichen Abhaengigkeiten.

Alle BLE-/Netz-Aufgaben laufen in einem Hintergrund-Thread mit eigenem asyncio-Loop; die GUI bleibt bedienbar.
"""
from __future__ import annotations

import asyncio
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

from . import DEFAULT_ADDRESS, DEFAULT_SKU, __version__
from .eventlog import Event, EventLog


class Worker:
    """Ein Hintergrund-Thread mit Dauer-Loop; Coroutinen werden eingereicht, Ergebnisse per Callback."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coro, on_done: Callable[[Any, Exception | None], None]) -> None:
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)

        def cb(f) -> None:
            try:
                on_done(f.result(), None)
            except Exception as exc:  # noqa: BLE001
                on_done(None, exc)

        fut.add_done_callback(cb)


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title(f"Govee Lab {__version__} – H6630 Diagnose & Steuerung")
        root.geometry("1120x720")
        self.log = EventLog()
        self.worker = Worker()
        self.lab = None  # BleLab, lazy
        self.busy = False
        self.event_q: queue.Queue[Event] = queue.Queue()
        self.log.subscribe(self.event_q.put)
        self._found_ip: str | None = None

        self._build()
        self.root.after(120, self._drain_events)
        self.log.info("app", f"Govee Lab {__version__} bereit. Geraet: {DEFAULT_SKU} {DEFAULT_ADDRESS}")

    # ---------------------------------------------------------------- Aufbau
    def _build(self) -> None:
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="BLE-Adresse:").pack(side="left")
        self.addr = tk.StringVar(value=DEFAULT_ADDRESS)
        ttk.Entry(top, textvariable=self.addr, width=22).pack(side="left", padx=6)
        ttk.Label(top, text="IP (LAN):").pack(side="left")
        self.ip = tk.StringVar(value="")
        ttk.Entry(top, textvariable=self.ip, width=16).pack(side="left", padx=6)
        self.status = tk.StringVar(value="bereit")
        ttk.Label(top, textvariable=self.status, foreground="#0a7").pack(side="right")

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=8, pady=4)
        self._tab_connect(nb)
        self._tab_known(nb)
        self._tab_experimental(nb)
        self._tab_lan(nb)
        self._tab_cloud(nb)

        # Paketansicht unten
        bottom = ttk.LabelFrame(self.root, text="Pakete & Protokoll (Hex, erkannte Felder, Ergebnis)", padding=4)
        bottom.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        cols = ("zeit", "kanal", "art", "inhalt", "hex")
        self.tree = ttk.Treeview(bottom, columns=cols, show="headings", height=12)
        for c, w in zip(cols, (90, 55, 70, 560, 300)):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="w")
        vs = ttk.Scrollbar(bottom, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        bar = ttk.Frame(self.root)
        bar.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(bar, text="Diagnosepaket exportieren", command=self.on_export).pack(side="left")
        ttk.Button(bar, text="Protokoll leeren (Ansicht)", command=lambda: self.tree.delete(
            *self.tree.get_children())).pack(side="left", padx=6)
        ttk.Label(bar, text=f"Logdatei: {self.log.path}").pack(side="right")

    def _tab_connect(self, nb: ttk.Notebook) -> None:
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="Suche & Diagnose")
        ttk.Button(f, text="BLE-Suche (Govee)", command=self.on_scan).grid(row=0, column=0, sticky="w", pady=3)
        ttk.Button(f, text="GATT-Dienste anzeigen (nur lesen)", command=self.on_gatt).grid(row=1, column=0, sticky="w", pady=3)
        ttk.Button(f, text="Notifications 20 s mitschneiden", command=self.on_monitor).grid(row=2, column=0, sticky="w", pady=3)
        ttk.Separator(f, orient="horizontal").grid(row=3, column=0, columnspan=3, sticky="ew", pady=8)
        ttk.Label(f, text="Lesebefehle (0xAA, keine Aenderung am Geraet):").grid(row=4, column=0, sticky="w")
        self.read_vars: dict[str, tk.BooleanVar] = {}
        from .ble import read_catalog
        for i, (key, (_frame, label)) in enumerate(read_catalog().items()):
            v = tk.BooleanVar(value=key in ("soft_version", "hard_version", "power", "brightness"))
            self.read_vars[key] = v
            ttk.Checkbutton(f, text=f"{key} – {label}", variable=v).grid(row=5 + i, column=0, sticky="w")
        ttk.Button(f, text="Ausgewaehlte lesen", command=self.on_read).grid(row=5, column=1, sticky="w", padx=20)

    def _tab_known(self, nb: ttk.Notebook) -> None:
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="Bekannte Befehle")
        ttk.Label(f, text="Fuer H6630 in govee-ble-local vorgesehen: Ein/Aus, Helligkeit.").grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Button(f, text="Einschalten", command=lambda: self.on_known("on")).grid(row=1, column=0, pady=6, padx=3)
        ttk.Button(f, text="Ausschalten", command=lambda: self.on_known("off")).grid(row=1, column=1, pady=6, padx=3)
        self.bright = tk.IntVar(value=50)
        ttk.Scale(f, from_=1, to=100, variable=self.bright, orient="horizontal", length=240).grid(row=2, column=0, columnspan=2, sticky="w")
        ttk.Label(f, textvariable=self.bright).grid(row=2, column=2)
        ttk.Button(f, text="Helligkeit setzen", command=lambda: self.on_known("brightness", self.bright.get())).grid(row=2, column=3)
        ttk.Label(f, text="Ein gesendetes Paket ist kein Beweis. Ergebnis zeigt gesendet/quittiert/abgelehnt – "
                          "sichtbare Wirkung bitte am Geraet pruefen.", foreground="#a60").grid(row=3, column=0, columnspan=4, sticky="w", pady=8)

    def _tab_experimental(self, nb: ttk.Notebook) -> None:
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="Experimente")
        ttk.Label(f, text="Begruendete Einzelversuche. Jeder Versuch erst nach Bestaetigung. Keine fremde "
                          "Firmware, kein Fuzzing.", foreground="#a60").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(f, text="Zeit-Sync (33 09) mit Zeitzone UTC:").grid(row=1, column=0, sticky="w", pady=10)
        self.tz = tk.IntVar(value=9)
        ttk.Spinbox(f, from_=-12, to=14, textvariable=self.tz, width=5).grid(row=1, column=1, sticky="w")
        ttk.Button(f, text="Zeit-Sync senden", command=self.on_timesync).grid(row=1, column=2, padx=10)
        ttk.Label(f, text="Prueft, ob sich die Geraeteuhr per BLE stellen laesst (offene Frage Zeitquelle).").grid(row=2, column=0, columnspan=3, sticky="w")

    def _tab_lan(self, nb: ttk.Notebook) -> None:
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="LAN")
        ttk.Button(f, text="LAN-Scan (Multicast + Unicast)", command=self.on_lan_scan).grid(row=0, column=0, sticky="w", pady=3)
        ttk.Button(f, text="devStatus abfragen (IP oben)", command=self.on_lan_status).grid(row=1, column=0, sticky="w", pady=3)
        ttk.Button(f, text="Geraet im Netz finden (ARP)", command=self.on_arp).grid(row=2, column=0, sticky="w", pady=3)
        ttk.Label(f, text="Die Govee-LAN-API (UDP 4001/4002/4003) ist nur erreichbar, wenn die LAN-Steuerung am "
                          "Geraet aktiv ist. Fehler werden im Protokoll erklaert.").grid(row=3, column=0, sticky="w", pady=8)

    def _tab_cloud(self, nb: ttk.Notebook) -> None:
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="Cloud")
        ttk.Label(f, text="Offizielle Govee-Developer-API. API-Key wird lokal (DPAPI) gespeichert.").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(f, text="API-Key:").grid(row=1, column=0, sticky="w", pady=6)
        self.api_key = tk.StringVar()
        ttk.Entry(f, textvariable=self.api_key, width=44, show="*").grid(row=1, column=1, sticky="w")
        ttk.Button(f, text="Key speichern", command=self.on_save_key).grid(row=1, column=2, padx=6)
        self.cloud_state = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="auch aktuellen Zustand abfragen", variable=self.cloud_state).grid(row=2, column=1, sticky="w")
        ttk.Button(f, text="H6630-Capabilities abfragen", command=self.on_cloud).grid(row=3, column=1, sticky="w", pady=8)

    # ---------------------------------------------------------------- Helfer
    def _lab(self):
        if self.lab is None:
            from .ble import BleLab
            self.lab = BleLab(self.log)
        return self.lab

    def _run(self, coro, name: str) -> None:
        if self.busy:
            messagebox.showinfo("Bitte warten", "Es laeuft bereits eine Aufgabe.")
            return
        self.busy = True
        self.status.set(f"{name} laeuft ...")

        def done(result: Any, exc: Exception | None) -> None:
            self.busy = False
            if exc is not None:
                self.log.error("app", f"{name}: {type(exc).__name__}: {exc}")
                self.root.after(0, lambda: self.status.set(f"{name}: Fehler"))
            else:
                self.root.after(0, lambda: self.status.set(f"{name}: fertig"))

        self.worker.submit(coro, done)

    def _drain_events(self) -> None:
        try:
            while True:
                ev = self.event_q.get_nowait()
                content = ev.summary
                if ev.fields:
                    extra = " ".join(f"{k}={v}" for k, v in ev.fields.items()
                                     if k not in ("request", "replies", "acks", "raw", "capabilities", "state"))
                    content = f"{content}   {extra}" if extra else content
                tag = ev.kind
                self.tree.insert("", "end", values=(ev.time_str, ev.channel, ev.kind, content[:400],
                                                     (ev.hex or "")[:120]), tags=(tag,))
                self.tree.see(self.tree.get_children()[-1])
                if ev.channel == "lan" and ev.kind == "result" and "ARP" in ev.summary and ev.fields.get("exact") == "True":
                    self._found_ip = ev.fields.get("ip")
                    self.root.after(0, lambda ip=self._found_ip: self.ip.set(ip))
        except queue.Empty:
            pass
        self.tree.tag_configure("error", foreground="#c00")
        self.tree.tag_configure("warn", foreground="#a60")
        self.tree.tag_configure("result", foreground="#06a")
        self.tree.tag_configure("tx", foreground="#555")
        self.root.after(150, self._drain_events)

    # ---------------------------------------------------------------- Aktionen
    def on_scan(self) -> None:
        self._run(self._lab().scan(8.0, True), "BLE-Suche")

    def on_gatt(self) -> None:
        self._run(self._lab().gatt_probe(self.addr.get(), True), "GATT")

    def on_monitor(self) -> None:
        self._run(self._lab().monitor(self.addr.get(), 20.0), "Mitschnitt")

    def on_read(self) -> None:
        from .ble import read_catalog
        cat = read_catalog()
        chosen = [k for k, v in self.read_vars.items() if v.get()]

        async def run() -> None:
            for k in chosen:
                frame, label = cat[k]
                await self._lab().read(self.addr.get(), frame, label)

        self._run(run(), "Lesen")

    def on_known(self, command: str, value: int | None = None) -> None:
        if command == "off" and not messagebox.askyesno("Bestaetigen", "Geraet ausschalten?"):
            return
        self._run(self._lab().send_known(self.addr.get(), command, value), f"Befehl {command}")

    def on_timesync(self) -> None:
        from .ble import time_sync_frame
        tz = self.tz.get()
        frame = time_sync_frame(tz)
        if not messagebox.askyesno("Experiment bestaetigen",
                                   f"33 09 Zeit-Sync mit Zone UTC{tz:+d} senden?\nFrame: {frame.hex()}"):
            return
        self._run(self._lab().send_experimental(self.addr.get(), frame, f"sync_time UTC{tz:+d}"), "Zeit-Sync")

    def on_lan_scan(self) -> None:
        from .lan import scan
        ip = self.ip.get().strip() or None

        async def run() -> None:
            scan(self.log, 5.0, ip)

        self._run(run(), "LAN-Scan")

    def on_lan_status(self) -> None:
        from .lan import dev_status
        ip = self.ip.get().strip()
        if not ip:
            messagebox.showinfo("IP fehlt", "Bitte IP oben eintragen (oder per ARP finden).")
            return

        async def run() -> None:
            dev_status(self.log, ip)

        self._run(run(), "devStatus")

    def on_arp(self) -> None:
        from .lan import arp_govee
        from .ble import read_catalog  # noqa: F401

        async def run() -> None:
            arp_govee(self.log, None)

        self._run(run(), "ARP")

    def on_save_key(self) -> None:
        from . import config
        key = self.api_key.get().strip()
        if key:
            config.set_secret("govee_api_key", key)
            self.api_key.set("")
            self.log.info("cloud", "API-Key lokal gespeichert (DPAPI).")

    def on_cloud(self) -> None:
        from . import cloud

        async def run() -> None:
            cloud.query_h6630(self.log, DEFAULT_SKU, self.cloud_state.get())

        self._run(run(), "Cloud")

    def on_export(self) -> None:
        from .export import export_bundle

        async def run() -> None:
            export_bundle(self.log)

        self._run(run(), "Export")


def run() -> int:
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0
