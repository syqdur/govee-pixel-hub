"""Lokaler, verschluesselter Speicher fuer Geheimnisse (API-Key) via Windows DPAPI.

Der Klartext verlaesst nie den PC und wird mit dem Windows-Benutzerkonto verschluesselt (CryptProtectData).
Faellt DPAPI aus (z. B. Nicht-Windows), wird nur mit Warnung im Klartext abgelegt."""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from .eventlog import data_dir

_STORE = None


def _store_path() -> Path:
    return data_dir() / "secrets.json"


def _dpapi(data: bytes, encrypt: bool) -> bytes | None:
    try:
        import ctypes
        from ctypes import wintypes

        class BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        blob_in = BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)),
                                              ctypes.POINTER(ctypes.c_char)))
        blob_out = BLOB()
        fn = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
        flags = 0x01  # CRYPTPROTECT_UI_FORBIDDEN
        if not fn(ctypes.byref(blob_in), None, None, None, None, flags, ctypes.byref(blob_out)):
            return None
        out = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        kernel32.LocalFree(blob_out.pbData)
        return out
    except Exception:  # noqa: BLE001 - kein DPAPI verfuegbar
        return None


def _load() -> dict[str, Any]:
    p = _store_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save(store: dict[str, Any]) -> None:
    _store_path().write_text(json.dumps(store, indent=2), encoding="utf-8")


def set_secret(name: str, value: str) -> None:
    enc = _dpapi(value.encode("utf-8"), True)
    store = _load()
    if enc is not None:
        store[name] = {"dpapi": base64.b64encode(enc).decode()}
    else:
        store[name] = {"plain": value, "warnung": "DPAPI nicht verfuegbar: Klartext gespeichert"}
    _save(store)


def get_secret(name: str) -> str | None:
    entry = _load().get(name)
    if not entry:
        return None
    if "dpapi" in entry:
        dec = _dpapi(base64.b64decode(entry["dpapi"]), False)
        return dec.decode("utf-8") if dec else None
    return entry.get("plain")


def get_setting(name: str, default: Any = None) -> Any:
    return _load().get("_settings", {}).get(name, default)


def set_setting(name: str, value: Any) -> None:
    store = _load()
    store.setdefault("_settings", {})[name] = value
    _save(store)
