"""Experimental H6630 effect encoding; this module never connects to a device.

Protocol notes from H6630 APK reverse-engineering:
7.7.21 h6630-jadx/.../detail/diy/parser/H663XCellGraffitiParse.java
  makeBleController: MtuOpInfo(true, 0x58, toBytes()).
6.6.01 old-classes10.dex/.../widget/graffiti/new_protocol/
  AbsCellGraffitiDataParse.toBytes, CellGraffitiDataNewProtocol.e,
  LayersInfo.m, LayerPaintingData.i, LayerBase.c.
6.6.01 old-classes8.dex/.../ble/comm/MultipleControllerCommV1.java
  makeSendBytesMtu: variable-length A4 packets with XOR checksums.

These encode finite effects, not an established framebuffer streaming API.
Shared parser details are from an older app; hardware acceptance must be tested.
"""
import io
from functools import reduce
from operator import xor

from PIL import Image


def _le16(value):
    return value.to_bytes(2, "little")


def _checksum(data):
    return bytes(data) + bytes([reduce(xor, data, 0)])


def png_frame(image, background=(0, 0, 0), brightness=100):
    """Return 5E graffiti effect data with one full-size PNG painting layer.

    The returned payload is passed to A4 command 58, without the cloud's 58 00
    wrapper. PNG image encoding replaces GIF, but does not prove live updates.
    """
    if image.size != (32, 32):
        raise ValueError("H6630 frame must be exactly 32x32")
    if len(background) != 3 or any(not 0 <= c <= 255 for c in background):
        raise ValueError("Background must contain three RGB bytes")
    if not 1 <= brightness <= 100:
        raise ValueError("Brightness must be between 1 and 100")
    stream = io.BytesIO()
    image.convert("RGB").save(stream, format="PNG", optimize=True)
    png = stream.getvalue()
    # LayerBase defaults: action, speed, duration, layer index, size LE16,
    # two further effect flags. The original app uses size=100.
    common = b"\x00\x32\x64\x01\x64\x00\x00\x00"
    record = b"\x00" + _le16(len(png)) + png + common
    # effect, background, brightness, showType=0, no intro,
    # one main painting layer, no outro.
    return (b"\x5e" + bytes(background) + bytes([brightness, 0, 0, 1])
            + _le16(len(record)) + record + b"\x00")


def gif_frame(raw):
    """Return 5D + GIF89a bytes, the app's alternate finite effect format."""
    if not raw.startswith(b"GIF89a"):
        raise ValueError("Expected GIF89a")
    with Image.open(io.BytesIO(raw)) as image:
        if image.size != (32, 32):
            raise ValueError("H6630 frame must be exactly 32x32")
    return b"\x5d" + raw


def mtu_packets(payload, mtu_size=244, command=0x58, protocol=0xA4):
    """Port of makeSendBytesMtu, not the separate makeSendBytesMtuV1.

    mtu_size is the available characteristic VALUE size, not negotiated ATT MTU.
    App's admitted interval is 20..512. The caller must use the actual supported
    write size; 244 is merely a default and has not been measured on this H6630.
    """
    if not 20 <= mtu_size <= 512:
        raise ValueError("Available characteristic value size must be 20..512")
    if not 0 <= command <= 255 or not 0 <= protocol <= 255:
        raise ValueError("Protocol and command must be bytes")
    payload = bytes(payload)
    first_capacity, capacity = mtu_size - 8, mtu_size - 4
    if len(payload) <= first_capacity:
        return [_checksum(bytes([protocol, 0, 0, 1, 2, 0, command]) + payload),
                _checksum(bytes([protocol, 255, 255]))]
    remaining = len(payload) - first_capacity
    count = 1 + (remaining + capacity - 1) // capacity
    if count > 65535:
        raise ValueError("Effect requires too many packets")
    packets = [_checksum(bytes([protocol, 0, 0, 1]) + _le16(count)
                         + bytes([command]) + payload[:first_capacity])]
    position = first_capacity
    for index in range(1, count):
        chunk = payload[position:position + capacity]
        sequence = 65535 if index == count - 1 else index
        packets.append(_checksum(bytes([protocol]) + _le16(sequence) + chunk))
        position += len(chunk)
    return packets


def mtu_acknowledgement(reply, command=0x58):
    """None for unrelated notify; otherwise validated device result byte.

    ControllerMTUMulti uses A4/command identity and inherits result position2
    from AbsControllerNoEvent4Multi. Result0 means success in that source.
    """
    reply = bytes(reply)
    if len(reply) < 2 or reply[:2] != bytes([0xA4, command]):
        return None
    if len(reply) != 20 or reduce(xor, reply, 0):
        raise ValueError("Malformed MTU acknowledgement")
    return reply[2]


def a3_packets(payload, command=0x58):
    """Fixed20-byte makeSendBytesV1/2 packets, used by H6630DiyParser IoT.

    This fallback is a transport experiment for PNG frames; the current app's
    PNG parser itself selects its large-effect transport rather than this path.
    """
    payload = bytes(payload)
    if not 0 <= command <= 255:
        raise ValueError("Command must be a byte")
    tail = payload[14:]
    count = max(2, 1 + (len(tail) + 16) // 17)
    if count > 255:
        raise ValueError("A3 effect requires more than 255 packets")
    first = bytearray(19)
    first[:5] = bytes([0xA3, 0, 1, count, command])
    first[5:5 + min(14, len(payload))] = payload[:14]
    packets = [_checksum(first)]
    for index in range(1, count):
        fragment = bytearray(19)
        fragment[:2] = bytes([0xA3, 255 if index == count - 1 else index])
        chunk = tail[(index - 1) * 17:index * 17]
        fragment[2:2 + len(chunk)] = chunk
        packets.append(_checksum(fragment))
    return packets
