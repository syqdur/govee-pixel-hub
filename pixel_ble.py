"""Direct finite H6630 image transfers over one Bluetooth connection.

The A4/58 transfer and 33/05 activation were acknowledged on Mauro's H6630.
This is an app-derived effect transfer, not an undocumented raw framebuffer.
"""
import argparse
import asyncio
import base64
import io
import time

from bleak import BleakScanner
from govee_ble_local import Encryption, bound_advertisement
from govee_ble_local.transport.connection import GoveeConnection, UploadUnit
from PIL import Image

from diy_bridge import read_state
from pixel_frame import gif_frame, mtu_packets, png_frame

ADDRESS = "CC:B8:5E:BE:0F:99"


def single_image(image):
    output = io.BytesIO()
    image.convert("RGB").save(output, format="GIF", save_all=True, duration=100, loop=0)
    return gif_frame(output.getvalue())


def command(code, payload):
    frame = bytearray(bytes([0x33, code]) + bytes(payload).ljust(17, b"\0"))
    checksum = 0
    for value in frame:
        checksum ^= value
    return bytes(frame) + bytes([checksum])


class BlePixelClient:
    def __init__(self):
        self.connection = None
        self.cached_device = None
        self.cached_info = None
        self.activated = False

    def _get_secret(self):
        config = read_state().get("pixel_ble", {})
        secret = base64.b64decode(config.get("secretCode", ""), validate=True)
        if secret and len(secret) != 8:
            raise RuntimeError("Invalid saved device pairing key length")
        return secret

    async def connect(self):
        secret = self._get_secret()
        unlock = (lambda: [command(0xB2, secret)]) if secret else None

        if self.cached_device is None:
            from bleak.backends.device import BLEDevice
            self.cached_device = BLEDevice(ADDRESS, "Govee_H6630_0F99", None)

        self.connection = GoveeConnection(
            self.cached_device,
            encryption=Encryption.AES_RC4_PSK,
            unlock_frames=unlock,
            idle_disconnect=86400.0,
        )
        await self.connection.connect()

    async def send_image(self, image, encoding="gif"):
        if image.size != (32, 32):
            raise ValueError("H6630 image must be 32x32")
        payload = png_frame(image) if encoding == "png" else single_image(image)
        return await self.send_payload(payload)

    async def send_payload(self, payload):
        if self.connection is None:
            await self.connect()
        started = time.monotonic()
        await self.connection.send_unacked(
            lambda size: mtu_packets(payload, min(size, 244)), before=5,
            unit=UploadUnit(0xA4, 0x58, 2, .065))
        if not self.activated:
            await self.connection.send(command(5, b"\x0a\xfe\x00"))
            self.activated = True
        return {"transport": "ble", "ack": "a4 58 00",
                "bytes": len(payload), "seconds": round(time.monotonic() - started, 3)}

    async def turn_off(self):
        """Turn off the H6630 display LEDs."""
        if self.connection is None:
            await self.connect()
        await self.connection.send(command(1, b"\x00"), expect_ack=False)

    async def turn_on(self):
        """Turn on the H6630 display LEDs."""
        if self.connection is None:
            await self.connect()
        await self.connection.send(command(1, b"\x01"), expect_ack=False)

    async def close(self):
        if self.connection is not None:
            try:
                await self.connection.close()
            except Exception:
                pass
            self.connection = None
            self.activated = False
        self.cached_device = None


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    parser.add_argument("--encoding", choices=["gif", "png"], default="gif")
    args = parser.parse_args()
    client = BlePixelClient()
    try:
        with Image.open(args.image) as image:
            result = await client.send_image(image.convert("RGB"), args.encoding)
        print(result)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
