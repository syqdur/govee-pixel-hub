"""Bluetooth-LE-Zugriff auf den H6630: Suche, GATT-Diagnose, Notification-Mitschnitt, dokumentierte Befehle.

Grundsaetze:
- Keine zufaelligen Schreibbefehle. Jeder Frame stammt aus govee-ble-local (aus der Govee-App abgeleitet).
- Ein gesendeter Frame ist kein Erfolg: das Ergebnis unterscheidet "gesendet", "quittiert", "keine Antwort",
  "abgelehnt". Sichtbare Wirkung kann nur der Nutzer bestaetigen.
- Der Sitzungsschluessel des verschluesselten Kanals wird nie geloggt (die Bibliothek gibt ihn nicht heraus).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from . import DEFAULT_SKU
from .eventlog import ACKED, NO_REPLY, REJECTED, SENT, EventLog
from .frames import decode

GOVEE_SERVICE = "00010203-0405-0607-0809-0a0b0c0d1910"
CHAR_NOTIFY = "00010203-0405-0607-0809-0a0b0c0d2b10"
CHAR_WRITE = "00010203-0405-0607-0809-0a0b0c0d2b11"


@dataclass
class Found:
    device: BLEDevice
    adv: AdvertisementData
    info: dict[str, Any] = field(default_factory=dict)


class _FrameTap(logging.Handler):
    """Haengt sich an den Logger govee_ble_local.frames und uebertraegt jeden TX/RX-Frame ins Ereignisprotokoll."""

    def __init__(self, log: EventLog) -> None:
        super().__init__(logging.DEBUG)
        self.log = log
        self.rx: list[bytes] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            args = record.args if isinstance(record.args, tuple) else ()
            if len(args) == 6:
                addr, direction, label, plain, wire, enc = args
                plain_b = bytes.fromhex(plain) if plain else b""
            elif len(args) == 5:
                addr, direction, label, wire, enc = args
                plain, plain_b = "", b""
            else:
                return
            wire_hex = wire.hex() if isinstance(wire, (bytes, bytearray)) else str(wire)
            if plain_b:
                d = decode(plain_b, direction)
                summary = d.text()
                fields = dict(d.fields)
                if direction == "rx":
                    self.rx.append(plain_b)
            else:
                summary = f"{label} (Klartext nicht verfuegbar: Handshake/verschluesselt)"
                fields = {}
            self.log.add("ble", direction, summary, hex=plain_b.hex() or None, wire=wire_hex,
                         enc=str(enc), **fields)
        except Exception as exc:  # noqa: BLE001
            self.log.warn("ble", f"Frame-Protokoll fehlgeschlagen: {exc}")


class BleLab:
    def __init__(self, log: EventLog, sku: str = DEFAULT_SKU) -> None:
        self.log = log
        self.sku = sku
        self.found: dict[str, Found] = {}
        self._tap = _FrameTap(log)
        lg = logging.getLogger("govee_ble_local.frames")
        lg.setLevel(logging.DEBUG)
        lg.addHandler(self._tap)
        lg.propagate = False

    # ---------------------------------------------------------------- Suche
    async def scan(self, timeout: float = 8.0, only_govee: bool = True) -> list[Found]:
        self.log.info("ble", f"Suche BLE-Geraete ({timeout:.0f} s) ...")
        try:
            results = await BleakScanner.discover(timeout=timeout, return_adv=True)
        except Exception as exc:  # noqa: BLE001
            self.log.error("ble", f"Bluetooth-Suche fehlgeschlagen: {exc}. Ist Bluetooth eingeschaltet?")
            return []
        out = []
        for device, adv in results.values():
            name = adv.local_name or device.name or ""
            is_govee = name.startswith(("Govee", "ihoment", "Minger", "GBK", "GVH")) or any(
                k in (0x8803, 0xEC88, 0x8802) for k in adv.manufacturer_data)
            if only_govee and not is_govee:
                continue
            info = self._adv_info(name, adv)
            f = Found(device, adv, info)
            self.found[device.address.upper()] = f
            out.append(f)
            self.log.add("ble", "rx", f"Werbung: {name or '?'} {device.address} RSSI {adv.rssi}",
                         **info)
        if not out:
            self.log.warn("ble", "Kein Govee-Geraet gefunden. Geraet eingeschaltet, in Reichweite und nicht "
                                 "gerade mit dem Handy verbunden?")
        return out

    def _adv_info(self, name: str, adv: AdvertisementData) -> dict[str, Any]:
        info: dict[str, Any] = {
            "name": name, "rssi": adv.rssi,
            "manufacturer": {f"0x{k:04x}": v.hex() for k, v in adv.manufacturer_data.items()},
            "service_uuids": list(adv.service_uuids),
        }
        try:
            from govee_ble_local import bound_advertisement
            ga = bound_advertisement(adv, self.sku, fallback_name=name)
            if ga is not None:
                info.update(encrypted=ga.encrypted, pact=f"{ga.pact_type},{ga.pact_code}"
                            if ga.pact_type is not None else None, broadcast_version=ga.broadcast_version)
        except Exception as exc:  # noqa: BLE001
            info["adv_parse_error"] = str(exc)
        return info

    async def _resolve(self, address: str) -> Found:
        key = address.upper()
        if key in self.found:
            return self.found[key]
        self.log.info("ble", f"Suche {address} ...")
        result: list[Found] = []

        def cb(device: BLEDevice, adv: AdvertisementData) -> None:
            # Erst ein Werbepaket mit Govee-Herstellerdaten verraet das Verschluesselungs-Flag.
            if device.address.upper() == key and not result:
                info = self._adv_info(adv.local_name or device.name or "", adv)
                if "encrypted" in info:
                    result.append(Found(device, adv, info))

        async with BleakScanner(cb):
            for _ in range(150):
                if result:
                    break
                await asyncio.sleep(0.1)
        if not result:
            raise RuntimeError(f"{address} nicht gefunden. Geraet einschalten, Govee-App am Handy schliessen "
                               f"(eine bestehende Handy-Verbindung blockiert BLE).")
        self.found[key] = result[0]
        return result[0]

    # ---------------------------------------------------------------- GATT
    async def gatt_probe(self, address: str, read_values: bool = True) -> list[dict[str, Any]]:
        """Listet Dienste/Characteristics/Deskriptoren. Liest nur lesbare Characteristics, schreibt nichts."""
        found = await self._resolve(address)
        dump: list[dict[str, Any]] = []
        async with BleakClient(found.device, timeout=20) as client:
            self.log.info("gatt", f"Verbunden: {client.is_connected}, MTU {getattr(client, 'mtu_size', '?')}")
            for service in client.services:
                srv = {"uuid": service.uuid, "description": service.description, "characteristics": []}
                for ch in service.characteristics:
                    entry: dict[str, Any] = {"uuid": ch.uuid, "handle": ch.handle,
                                             "properties": list(ch.properties),
                                             "descriptors": [d.uuid for d in ch.descriptors]}
                    if read_values and "read" in ch.properties:
                        try:
                            value = await client.read_gatt_char(ch)
                            entry["value_hex"] = bytes(value).hex()
                            entry["value_ascii"] = bytes(value).decode("ascii", "replace") if all(
                                32 <= b < 127 for b in value) and value else None
                        except Exception as exc:  # noqa: BLE001
                            entry["read_error"] = str(exc)
                    srv["characteristics"].append(entry)
                    self.log.add("gatt", "info", f"{service.uuid} / {ch.uuid} [{', '.join(ch.properties)}]",
                                 hex=entry.get("value_hex"), handle=ch.handle,
                                 read_error=entry.get("read_error"))
                dump.append(srv)
        self.log.info("gatt", "GATT-Diagnose beendet. Es wurde nichts geschrieben.")
        return dump

    async def monitor(self, address: str, seconds: float = 30.0) -> int:
        """Abonniert alle notify-Characteristics und protokolliert Rohdaten. Schreibt nichts.

        Hinweis: ohne Handshake sendet ein verschluesseltes Govee-Geraet in der Regel nichts; die Rohdaten
        waeren ohnehin Chiffretext."""
        found = await self._resolve(address)
        count = 0

        def handler(char: Any, data: bytearray) -> None:
            nonlocal count
            count += 1
            raw = bytes(data)
            d = decode(raw, "rx")
            self.log.add("gatt", "rx", f"Notification {getattr(char, 'uuid', char)}: {d.text()}",
                         hex=raw.hex(), length=len(raw))

        async with BleakClient(found.device, timeout=20) as client:
            chars = [c for s in client.services for c in s.characteristics if "notify" in c.properties]
            for c in chars:
                await client.start_notify(c, handler)
                self.log.info("gatt", f"Notifications aktiv: {c.uuid}")
            self.log.info("gatt", f"Lausche {seconds:.0f} s (keine Schreibzugriffe) ...")
            await asyncio.sleep(seconds)
            for c in chars:
                try:
                    await client.stop_notify(c)
                except Exception:  # noqa: BLE001
                    pass
        self.log.info("gatt", f"Mitschnitt beendet: {count} Notifications.")
        return count

    # ---------------------------------------------------------------- Protokoll
    def _encryption(self, found: Found):
        from govee_ble_local import Encryption
        enc = found.info.get("encrypted")
        if enc is None:
            raise RuntimeError("Verschluesselungs-Flag unbekannt (keine Govee-Herstellerdaten empfangen)")
        return Encryption.AES_RC4_PSK if enc else Encryption.NONE

    async def read(self, address: str, frame: bytes, label: str, timeout: float = 3.0) -> dict[str, Any]:
        """Ein dokumentierter 0xAA-Lesebefehl in einer eigenen Sitzung (Handshake durch die Bibliothek)."""
        from govee_ble_local.transport.connection import GoveeConnection
        found = await self._resolve(address)
        conn = GoveeConnection(found.device, encryption=self._encryption(found), idle_disconnect=2.0)
        self.log.add("ble", "info", f"Lesebefehl {label}: Sitzung aufbauen ...", hex=frame.hex())
        result: dict[str, Any] = {"label": label, "request": frame.hex(), "status": SENT, "replies": []}
        try:
            replies = await conn.query(frame, timeout=timeout, opcode=frame[0], terminal=frame[1], idle_gap=None)
            matching = [r for r in replies if len(r) >= 2 and r[0] == frame[0] and r[1] == frame[1]]
            result["replies"] = [r.hex() for r in replies]
            if matching:
                result["status"] = ACKED
                result["decoded"] = decode(matching[-1], "rx").fields
            else:
                result["status"] = NO_REPLY
        except Exception as exc:  # noqa: BLE001
            result["status"] = "Fehler"
            result["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            try:
                await conn.close()
            except Exception:  # noqa: BLE001
                pass
        self.log.add("ble", "result", f"{label}: {result['status']}", **{k: v for k, v in result.items()
                                                                          if k not in ("label",)})
        return result

    async def send_known(self, address: str, command: str, value: int | None = None) -> dict[str, Any]:
        """Bekannte, ueber govee-ble-local fuer H6630 vorgesehene Befehle: on, off, brightness."""
        from govee_ble_local import create_device
        found = await self._resolve(address)
        before = len(self._tap.rx)
        result: dict[str, Any] = {"command": command, "value": value, "status": SENT}
        dev = create_device(found.device, self.sku, found.adv)
        try:
            if command == "on":
                await dev.turn_on()
            elif command == "off":
                await dev.turn_off()
            elif command == "brightness":
                if value is None or not 1 <= value <= 100:
                    raise ValueError("Helligkeit 1..100")
                await dev.set_brightness(value)
            else:
                raise ValueError(f"unbekannter Befehl {command}")
            acks = [r for r in self._tap.rx[before:] if r[0] == 0x33]
            if acks:
                result["status"] = ACKED if all(r[2] == 0 for r in acks) else REJECTED
                result["acks"] = [r.hex() for r in acks]
            else:
                result["status"] = SENT + ", " + NO_REPLY
        except Exception as exc:  # noqa: BLE001
            name = type(exc).__name__
            result["status"] = REJECTED if "Rejected" in name else "Fehler"
            result["error"] = f"{name}: {exc}"
        finally:
            try:
                await dev.stop()
            except Exception:  # noqa: BLE001
                pass
        result["hinweis"] = "Sichtbare Wirkung bitte am Geraet pruefen und im Protokoll bestaetigen."
        self.log.add("ble", "result", f"{command}{'' if value is None else ' ' + str(value)}: {result['status']}",
                     **result)
        return result

    async def send_experimental(self, address: str, frame: bytes, label: str) -> dict[str, Any]:
        """Ein einzelner, aus Quellen begruendeter 0x33-Schreibbefehl (nur nach Bestaetigung in der Oberflaeche)."""
        from govee_ble_local.transport.connection import GoveeConnection
        if frame[0] != 0x33:
            raise ValueError("Nur 0x33-Schreibframes")
        found = await self._resolve(address)
        before = len(self._tap.rx)
        conn = GoveeConnection(found.device, encryption=self._encryption(found), idle_disconnect=2.0)
        result: dict[str, Any] = {"label": label, "request": frame.hex(), "status": SENT}
        try:
            await conn.send_once(frame)
            acks = [r for r in self._tap.rx[before:] if r[0] == 0x33 and r[1] == frame[1]]
            if acks:
                result["status"] = ACKED if acks[-1][2] == 0 else REJECTED
                result["ack"] = acks[-1].hex()
            else:
                result["status"] = SENT + ", " + NO_REPLY
        except Exception as exc:  # noqa: BLE001
            name = type(exc).__name__
            result["status"] = REJECTED if "Rejected" in name else "Fehler"
            result["error"] = f"{name}: {exc}"
        finally:
            try:
                await conn.close()
            except Exception:  # noqa: BLE001
                pass
        self.log.add("ble", "result", f"EXPERIMENT {label}: {result['status']}", **result)
        return result


# ---------------------------------------------------------------- Befehlskataloge
def read_catalog() -> dict[str, tuple[bytes, str]]:
    """Dokumentierte Lesebefehle (0xAA). Fuer den H6630 ist eine Antwort NICHT vorab belegt."""
    from govee_ble_local.wire import build as b
    return {
        "soft_version": (b.soft_version_query(), "aa 06 Firmware-Version (ASCII)"),
        "hard_version": (b.device_info_query(3), "aa 07 03 Hardware-Version"),
        "wifi_soft_version": (b.wifi_soft_version_query(), "aa 21 WLAN-Firmware"),
        "wifi_hard_version": (b.wifi_hard_version_query(), "aa 20 WLAN-Hardware"),
        "wifi_mac": (b.wifi_mac_query(), "aa 14 WLAN-MAC"),
        "power": (b.power_query(), "aa 01 Ein/Aus-Status"),
        "brightness": (b.brightness_query(), "aa 04 Helligkeit"),
    }


def time_sync_frame(tz_hours: int, tz_minutes: int = 0, unix_ts: int | None = None) -> bytes:
    """33 09 datetime_epoch – die in govee-ble-local fuer goodsType 285 hinterlegte Zeit-Sync-Form.

    Die Wanduhrzeit wird fuer die angegebene Zone berechnet, damit ein Test mit fremder Zone sichtbar wird."""
    from govee_ble_local.wire import build as b
    ts = int(time.time()) if unix_ts is None else unix_ts
    local = time.gmtime(ts + tz_hours * 3600 + (tz_minutes if tz_hours >= 0 else -tz_minutes) * 60)
    return b.sync_time("datetime_epoch", ts, local, tz_hours, tz_minutes)
