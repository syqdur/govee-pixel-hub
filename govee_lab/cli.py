"""Kommandozeile fuer dieselben Funktionen wie die Oberflaeche (praktisch fuer Tests und Skripte)."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from . import DEFAULT_ADDRESS
from .eventlog import EventLog, console_printer


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="govee_lab", description="Govee H6630 Diagnose")
    p.add_argument("--address", default=DEFAULT_ADDRESS)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gui")
    s = sub.add_parser("scan"); s.add_argument("--all", action="store_true"); s.add_argument("--timeout", type=float, default=8)
    g = sub.add_parser("gatt"); g.add_argument("--no-read", action="store_true")
    m = sub.add_parser("monitor"); m.add_argument("--seconds", type=float, default=20)
    r = sub.add_parser("read"); r.add_argument("what", nargs="+", help="soft_version hard_version wifi_soft_version ...")
    k = sub.add_parser("known"); k.add_argument("command", choices=["on", "off", "brightness"]); k.add_argument("value", nargs="?", type=int)
    t = sub.add_parser("timesync", help="EXPERIMENT 33 09"); t.add_argument("--tz", type=int, required=True)
    t.add_argument("--yes", action="store_true", help="ohne Rueckfrage senden")
    ls = sub.add_parser("lan-scan"); ls.add_argument("--ip", help="zusaetzlich Unicast an diese IP"); ls.add_argument("--timeout", type=float, default=4)
    lst = sub.add_parser("lan-status"); lst.add_argument("ip")
    ar = sub.add_parser("arp", help="ARP-Tabelle nach Govee-MACs durchsuchen"); ar.add_argument("--mac", help="WLAN-MAC (aus aa 14)")
    c = sub.add_parser("cloud"); c.add_argument("--set-key", help="API-Key lokal (DPAPI) speichern"); c.add_argument("--state", action="store_true")
    e = sub.add_parser("export"); e.add_argument("--mask-mac", action="store_true")
    a = sub.add_parser("apk-scan"); a.add_argument("--apk", required=True); a.add_argument("--jadx-out")
    bt = sub.add_parser("capture", aliases=["btsnoop", "pklg"],
                        help="BLE-Mitschnitt analysieren (btsnoop ODER PacketLogger .pklg, nur lesen)")
    bt.add_argument("log")
    args = p.parse_args(argv)

    if args.cmd == "gui":
        from .gui import run
        return run()

    log = EventLog()
    log.subscribe(console_printer)

    async def go() -> object:
        if args.cmd in ("scan", "gatt", "monitor", "read", "known", "timesync"):
            from .ble import BleLab, read_catalog, time_sync_frame
            lab = BleLab(log)
            if args.cmd == "scan":
                return [f.info | {"address": f.device.address} for f in await lab.scan(args.timeout, not args.all)]
            if args.cmd == "gatt":
                return await lab.gatt_probe(args.address, not args.no_read)
            if args.cmd == "monitor":
                return await lab.monitor(args.address, args.seconds)
            if args.cmd == "read":
                cat = read_catalog()
                out = []
                for w in args.what:
                    frame, label = cat[w]
                    out.append(await lab.read(args.address, frame, label))
                return out
            if args.cmd == "known":
                return await lab.send_known(args.address, args.command, args.value)
            if args.cmd == "timesync":
                frame = time_sync_frame(args.tz)
                print(f"EXPERIMENT: 33 09 Zeit-Sync mit Zone UTC{args.tz:+d}: {frame.hex()}")
                if not args.yes and input("Senden? (ja/nein) ").strip().lower() != "ja":
                    return "abgebrochen"
                return await lab.send_experimental(args.address, frame, f"sync_time UTC{args.tz:+d}")
        if args.cmd == "lan-scan":
            from .lan import scan
            return scan(log, timeout=args.timeout, unicast_ip=args.ip)
        if args.cmd == "lan-status":
            from .lan import dev_status
            return dev_status(log, args.ip)
        if args.cmd == "arp":
            from .lan import arp_govee
            return arp_govee(log, args.mac)
        if args.cmd == "cloud":
            from . import cloud, config
            if args.set_key:
                config.set_secret("govee_api_key", args.set_key)
                log.info("cloud", "API-Key lokal gespeichert (DPAPI-verschluesselt).")
            return cloud.query_h6630(log, with_state=args.state)
        if args.cmd == "export":
            from .export import export_bundle
            return str(export_bundle(log, mask_mac=args.mask_mac))
        if args.cmd == "apk-scan":
            from analysis.apk_scan import run_scan
            return str(run_scan(args.apk, args.jadx_out, log))
        if args.cmd in ("capture", "btsnoop", "pklg"):
            sig = open(args.log, "rb").read(8)
            if sig.startswith(b"btsnoop\x00"):
                from analysis.btsnoop import analyze
            else:
                from analysis.pklg import analyze
            return analyze(args.log, log)
        return None

    try:
        result = asyncio.run(go())
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        log.error("app", f"{type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    print(f"Protokoll: {log.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
