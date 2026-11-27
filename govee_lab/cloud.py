"""Govee Developer Cloud API (offiziell, dokumentiert) – nur mit lokal hinterlegtem API-Key.

Fragt ausschliesslich ab, was Govee fuer das Konto/Geraet tatsaechlich anbietet:
  GET  https://openapi.api.govee.com/router/api/v1/user/devices        (Geraeteliste + Capabilities)
  POST https://openapi.api.govee.com/router/api/v1/device/state        (aktueller Zustand)

Es werden KEINE Capabilities erfunden. Antwortet Govee fuer den H6630 nur mit power/brightness, steht genau das
im Ergebnis. Der API-Key wird ueber config (DPAPI) geladen und in Logs ausgeblendet.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from . import DEFAULT_SKU
from .config import get_secret
from .eventlog import EventLog

OPENAPI = "https://openapi.api.govee.com"
DEVICES_PATH = "/router/api/v1/user/devices"
STATE_PATH = "/router/api/v1/device/state"


def _request(path: str, api_key: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    url = OPENAPI + path
    headers = {"Govee-API-Key": api_key, "Content-Type": "application/json"}
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 - feste HTTPS-URL
        return json.loads(resp.read().decode("utf-8"))


def _explain_http(exc: urllib.error.HTTPError) -> str:
    body = ""
    try:
        body = exc.read().decode("utf-8", "replace")[:300]
    except Exception:  # noqa: BLE001
        pass
    if exc.code == 401:
        return "401: API-Key ungueltig oder abgelaufen."
    if exc.code == 403:
        return "403: Zugriff verweigert (Key ohne Berechtigung)."
    if exc.code == 429:
        return "429: Govee-Ratenlimit erreicht. Spaeter erneut versuchen."
    return f"HTTP {exc.code}: {body}"


def query_h6630(log: EventLog, sku: str = DEFAULT_SKU, with_state: bool = False) -> dict[str, Any]:
    api_key = get_secret("govee_api_key")
    if not api_key:
        log.warn("cloud", "Kein API-Key hinterlegt. Zuerst: govee_lab cloud --set-key <KEY> "
                          "(Key aus Govee Home -> Einstellungen -> Apps mit API). Cloud-Abfrage uebersprungen.")
        return {"status": "kein API-Key"}
    out: dict[str, Any] = {"sku": sku}
    try:
        log.info("cloud", "Frage Geraeteliste der offiziellen Govee-Developer-API ab ...")
        devices = _request(DEVICES_PATH, api_key)
    except urllib.error.HTTPError as exc:
        log.error("cloud", _explain_http(exc))
        return {"status": "Fehler", "error": _explain_http(exc)}
    except Exception as exc:  # noqa: BLE001
        log.error("cloud", f"Netzwerkfehler: {type(exc).__name__}: {exc}")
        return {"status": "Fehler", "error": str(exc)}

    matches = [d for d in devices.get("data", []) if str(d.get("sku", "")).upper() == sku.upper()]
    log.info("cloud", f"Konto hat {len(devices.get('data', []))} Geraet(e), davon {len(matches)} x {sku}.")
    out["devices"] = matches
    for d in matches:
        caps = [{"type": c.get("type"), "instance": c.get("instance")} for c in d.get("capabilities", [])]
        log.add("cloud", "result", f"{sku} {d.get('device')}: angebotene Capabilities",
                device=d.get("device"), capabilities=caps)
        out.setdefault("capabilities", {})[d.get("device")] = caps
        if with_state:
            try:
                state = _request(STATE_PATH, api_key, {"requestId": "govee-lab",
                                 "payload": {"sku": sku, "device": d.get("device")}})
                out.setdefault("state", {})[d.get("device")] = state.get("payload")
                log.add("cloud", "result", f"{sku} {d.get('device')}: Zustand", state=state.get("payload"))
            except Exception as exc:  # noqa: BLE001
                log.warn("cloud", f"Zustand nicht abrufbar: {exc}")
    if not matches:
        log.warn("cloud", f"{sku} ist nicht in der Cloud-Geraeteliste. In Govee Home mit dem Konto verbunden, "
                          f"und LAN-/Cloud-Freigabe aktiv? Die Developer-API zeigt nur unterstuetzte Geraete.")
    out["status"] = "ok"
    return out
