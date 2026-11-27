"""Direct Bluetooth control for Mauro's H6630; no cloud or LAN API required."""
import argparse
import asyncio
import sys

from bleak import BleakClient, BleakScanner
from govee_ble_local import create_device

ADDRESS = "CC:B8:5E:BE:0F:99"


async def run(args):
    found = await BleakScanner.discover(timeout=10, return_adv=True)
    target = next(((d, adv) for d, adv in found.values()
                   if d.address.upper() == args.address.upper()), None)
    if target is None:
        raise RuntimeError("H6630 nicht gefunden. Gerät einschalten und Nähe prüfen.")
    device, adv = target
    print(f"Gefunden: {adv.local_name or device.name} ({device.address})")
    if args.command == "probe":
        async with BleakClient(device, timeout=15) as client:
            print(f"Bluetooth verbunden: {client.is_connected}")
            for service in client.services:
                print(f"Dienst: {service.uuid}")
                for char in service.characteristics:
                    print(f"  {char.uuid}: {', '.join(char.properties)}")
        print("Keine Steuerbefehle gesendet.")
        return
    control = create_device(device, "H6630", adv)
    try:
        if args.command == "on":
            await control.turn_on()
        elif args.command == "off":
            await control.turn_off()
        elif args.command == "brightness":
            await control.set_brightness(args.percent)
        print("Befehl gesendet. Anzeige am Gerät prüfen; kein bestätigter Readback.")
    finally:
        await control.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default=ADDRESS)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("probe", "on", "off"):
        commands.add_parser(name)
    brightness = commands.add_parser("brightness")
    brightness.add_argument("percent", type=int, choices=range(1, 101), metavar="1..100")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except (Exception, KeyboardInterrupt) as error:
        print(f"Abgebrochen: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
