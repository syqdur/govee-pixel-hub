"""Govee LAN API (offiziell dokumentiert): Erkennung per UDP und Statusabfrage.

- Scan:      {"msg":{"cmd":"scan",...}} an 239.255.255.250:4001 (Multicast) bzw. Geraete-IP:4001 (Unicast)
- Antworten: kommen an Port 4002 des PCs
- Status:    {"msg":{"cmd":"devStatus","data":{}}} an Geraete-IP:4003

Fehler werden in Klartext uebersetzt. Fehlende Antwort heisst nur "keine Antwort beobachtet", nicht "unmoeglich".
"""
from __future__ import annotations

import json
import re
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .eventlog import EventLog

MCAST = "239.255.255.250"
SCAN_PORT, LISTEN_PORT, CMD_PORT = 4001, 4002, 4003
SCAN_MSG = {"msg": {"cmd": "scan", "data": {"account_topic": "reserve"}}}
STATUS_MSG = {"msg": {"cmd": "devStatus", "data": {}}}
GOVEE_OUIS = ("cc-b8-5e", "d4-ad-fc", "a4-c1-38", "60-74-f4", "c4-27-28")


def _explain(exc: OSError) -> str:
    code = getattr(exc, "winerror", None) or exc.errno
    if code in (10048, 98):
        return (f"Port {LISTEN_PORT} ist belegt (WinError 10048). Ein anderes Programm (Govee Desktop, Home Assistant, "
                f"ein frueherer Lauf) empfaengt bereits Govee-Antworten. Dieses Programm schliessen.")
    if code in (10013,):
        return "Zugriff verweigert (WinError 10013): Firewall/Sicherheitssoftware blockiert den Socket."
    if code in (10051, 10065):
        return "Netz nicht erreichbar: keine passende Netzwerkschnittstelle/Route."
    return f"{type(exc).__name__}: {exc}"


def local_ipv4() -> list[str]:
    ips: set[str] = set()
    try:
        ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    try:  # Schnittstelle der Standardroute
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith(("127.", "169.254.")))


def default_ipv4() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            return s.getsockname()[0]
    except OSError:
        return None


def _listener(log: EventLog) -> socket.socket | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.bind(("0.0.0.0", LISTEN_PORT))
    except OSError as exc:
        log.error("lan", _explain(exc))
        sock.close()
        return None
    sock.settimeout(0.3)
    return sock


def _collect(log: EventLog, sock: socket.socket, timeout: float) -> list[dict[str, Any]]:
    replies = []
    end = time.time() + timeout
    while time.time() < end:
        try:
            data, addr = sock.recvfrom(4096)
        except socket.timeout:
            continue
        except OSError as exc:
            log.error("lan", _explain(exc))
            break
        text = data.decode("utf-8", "replace")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = {"raw": text}
        replies.append({"from": addr[0], "payload": payload})
        log.add("lan", "rx", f"Antwort von {addr[0]}:{addr[1]}", hex=data.hex()[:200], payload=payload)
    return replies


def scan(log: EventLog, timeout: float = 4.0, unicast_ip: str | None = None) -> list[dict[str, Any]]:
    sock = _listener(log)
    if sock is None:
        return []
    msg = json.dumps(SCAN_MSG).encode()
    try:
        ifaces = local_ipv4()
        log.info("lan", f"Lokale IPv4-Schnittstellen: {', '.join(ifaces) or 'keine'}")
        sent = 0
        for ip in ifaces:  # Multicast auf JEDER Schnittstelle (Docker/WSL/VPN-Adapter lenken sonst falsch)
            tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            try:
                tx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
                tx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
                tx.sendto(msg, (MCAST, SCAN_PORT))
                sent += 1
                log.add("lan", "tx", f"Scan Multicast via {ip} -> {MCAST}:{SCAN_PORT}", hex=msg.hex()[:120])
            except OSError as exc:
                log.warn("lan", f"Multicast via {ip} fehlgeschlagen: {_explain(exc)}")
            finally:
                tx.close()
        if unicast_ip:
            try:
                sock.sendto(msg, (unicast_ip, SCAN_PORT))
                log.add("lan", "tx", f"Scan Unicast -> {unicast_ip}:{SCAN_PORT}")
            except OSError as exc:
                log.warn("lan", f"Unicast an {unicast_ip} fehlgeschlagen: {_explain(exc)}")
        replies = _collect(log, sock, timeout)
    finally:
        sock.close()
    if replies:
        log.add("lan", "result", f"LAN-Scan: {len(replies)} Antwort(en).")
    else:
        log.add("lan", "result",
                "LAN-Scan: keine Antwort beobachtet. Moegliche Gruende: LAN-Steuerung am Geraet aus (beim H6630 "
                "verlangt die App ein Firmware-Update), Firewall blockiert eingehendes UDP 4002 fuer Python, "
                "Client-Isolation/Multicast-Filter im Router, PC in anderem Netz als das Geraet.",
                interfaces=local_ipv4(), unicast=unicast_ip)
    return replies


def dev_status(log: EventLog, ip: str, timeout: float = 3.0) -> list[dict[str, Any]]:
    sock = _listener(log)
    if sock is None:
        return []
    msg = json.dumps(STATUS_MSG).encode()
    try:
        sock.sendto(msg, (ip, CMD_PORT))
        log.add("lan", "tx", f"devStatus -> {ip}:{CMD_PORT}", hex=msg.hex()[:120])
        replies = _collect(log, sock, timeout)
    except OSError as exc:
        log.error("lan", _explain(exc))
        replies = []
    finally:
        sock.close()
    log.add("lan", "result", f"devStatus {ip}: {'Antwort' if replies else 'keine Antwort'}")
    return replies


# ---------------------------------------------------------------- Netzwerk-Lokalisierung
_ARP_LINE = re.compile(r"^\s*(\d+\.\d+\.\d+\.\d+)\s+([0-9a-f]{2}(?:-[0-9a-f]{2}){5})\s+(\w+)", re.IGNORECASE | re.M)


def arp_table() -> list[tuple[str, str]]:
    out = subprocess.run(["arp", "-a"], capture_output=True, text=True, errors="replace", timeout=10).stdout
    return [(m.group(1), m.group(2).lower()) for m in _ARP_LINE.finditer(out)]


def ping_sweep(log: EventLog, base_ip: str) -> None:
    """Fuellt die ARP-Tabelle: ein Ping an jede Adresse des eigenen /24-Netzes (nur ICMP im eigenen LAN)."""
    prefix = ".".join(base_ip.split(".")[:3])
    log.info("lan", f"Ping-Durchlauf {prefix}.1-254 zum Fuellen der ARP-Tabelle ...")

    def ping(i: int) -> None:
        subprocess.run(["ping", "-n", "1", "-w", "300", f"{prefix}.{i}"], capture_output=True, timeout=5)

    with ThreadPoolExecutor(64) as pool:
        list(pool.map(ping, range(1, 255)))


def arp_govee(log: EventLog, wifi_mac: str | None = None, sweep: bool = True) -> list[dict[str, str]]:
    target = wifi_mac.lower().replace(":", "-") if wifi_mac else None

    def match() -> list[dict[str, str]]:
        hits = []
        for ip, mac in arp_table():
            if (target and mac == target) or mac.startswith(GOVEE_OUIS):
                hits.append({"ip": ip, "mac": mac, "exact": str(bool(target and mac == target))})
        return hits

    hits = match()
    if not any(h["exact"] == "True" for h in hits) and sweep and (base := default_ipv4()):
        ping_sweep(log, base)
        hits = match()
    for h in hits:
        log.add("lan", "result", f"ARP: {h['ip']} hat MAC {h['mac']}" + (" (WLAN-MAC des H6630)" if h["exact"] == "True"
                                                                        else " (Govee-Herstellerkennung)"), **h)
    if not hits:
        log.warn("lan", "Keine Govee-MAC in der ARP-Tabelle. Geraet evtl. in anderem Netz/Gast-WLAN oder offline.")
    return hits
