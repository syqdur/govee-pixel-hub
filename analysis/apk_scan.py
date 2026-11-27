"""Gezielte, wiederholbare Analyse des Govee-Home-APK fuer die offenen Fragen zum H6630.

Liest NUR (keine Ausfuehrung des App-Codes). Nutzt – falls vorhanden – eine jadx-Dekompilierung, sonst nur die
im ZIP lesbaren Ressourcen/Assets. Die Treffer sind aus Quellen abgeleitete Hinweise, kein Beweis fuer das
Verhalten am Geraet (die iPhone-App kann abweichen).

Beantwortete Fragen (Stichwortsuche + Kontext):
  - Firmware-Update pruefen/starten, Auto-Upgrade steuern
  - Geraetezeit / Zeitzone
  - LAN-Steuerung unabhaengig vom App-Schalter
  - Streaming/Upload eigener Pixelbilder/Texte
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any

QUESTIONS = {
    "firmware_update": [r"\bota\b", r"firmware", r"upgrade", r"softVersion", r"hardVersion", r"versionSoft"],
    "auto_upgrade": [r"auto.?upgrad", r"autoUpgrade", r"02:00", r"06:00", r"upgradePlan", r"nightUpgrade"],
    "time_zone": [r"timeZone", r"timezone", r"syncTime", r"getTimeOffset", r"ControllerSyncTime", r"33 ?09"],
    "lan_control": [r"lan.?control", r"wifiControl", r"\b4001\b", r"\b4002\b", r"\b4003\b", r"239\.255\.255\.250",
                    r"openLan", r"local.?api"],
    "pixel_stream": [r"graffiti", r"diy", r"pixel", r"watch.?face", r"\bgif\b", r"a3 ?upload", r"0xA3",
                     r"matrix", r"32x32", r"upload"],
}


def _iter_text_members(apk: zipfile.ZipFile):
    for info in apk.infolist():
        name = info.filename
        if name.endswith((".xml", ".json", ".properties", ".proto", ".txt")) and info.file_size < 4_000_000:
            try:
                yield name, apk.read(name).decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                continue


def _scan_text(name: str, text: str, hits: dict[str, list[dict[str, Any]]], per_q: int = 8) -> None:
    low = text.lower()
    for q, patterns in QUESTIONS.items():
        if len(hits[q]) >= per_q:
            continue
        for pat in patterns:
            for m in re.finditer(pat, text if any(c.isupper() for c in pat) else low, re.IGNORECASE):
                ctx = text[max(0, m.start() - 70):m.start() + 90].replace("\n", " ").strip()
                hits[q].append({"file": name, "pattern": pat, "context": ctx})
                if len(hits[q]) >= per_q:
                    break
            if len(hits[q]) >= per_q:
                break


def _scan_jadx(jadx_out: Path, hits: dict[str, list[dict[str, Any]]], per_q: int = 12) -> int:
    files = list(jadx_out.rglob("*.java")) + list(jadx_out.rglob("*.smali"))
    scanned = 0
    for f in files:
        if all(len(hits[q]) >= per_q for q in QUESTIONS):
            break
        try:
            text = f.read_text("utf-8", "replace")
        except Exception:  # noqa: BLE001
            continue
        scanned += 1
        _scan_text(str(f.relative_to(jadx_out)), text, hits, per_q)
    return scanned


def run_scan(apk_path: str, jadx_out: str | None, log: Any | None = None) -> Path:
    apk = Path(apk_path)
    hits: dict[str, list[dict[str, Any]]] = {q: [] for q in QUESTIONS}
    sources: dict[str, Any] = {"apk": str(apk), "jadx_out": jadx_out}

    if jadx_out and Path(jadx_out).exists():
        n = _scan_jadx(Path(jadx_out), hits)
        sources["jadx_java_files_scanned"] = n
        if log:
            log.info("analysis", f"jadx-Quellen durchsucht: {n} Dateien.")

    with zipfile.ZipFile(apk) as z:
        skus = {}
        for name, text in _iter_text_members(z):
            _scan_text(name, text, hits)
            if name.endswith("sku_ic.json"):
                try:
                    for row in json.loads(text):
                        if row.get("sku") in ("H6630", "H6631"):
                            skus[row["sku"]] = row.get("ic")
                except Exception:  # noqa: BLE001
                    pass
        sources["sku_ic"] = skus

    report = {
        "quellen": sources,
        "hinweis": "Aus der Android-App abgeleitet; kein Beweis fuer identisches Verhalten der iPhone-App "
                   "oder der konkreten Geraete-Firmware.",
        "funde": hits,
    }
    out = apk.parent / "apk-funde.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if log:
        for q in QUESTIONS:
            log.add("analysis", "result", f"APK-Frage '{q}': {len(hits[q])} Treffer.")
        log.info("analysis", f"APK-Funde gespeichert: {out}")
    return out
