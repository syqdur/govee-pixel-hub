"""Independent wire fixtures for the experimental finite-effect BLE encoder."""
import io
import unittest

from PIL import Image

from pixel_frame import a3_packets, mtu_acknowledgement, mtu_packets, png_frame


class PixelFrameTests(unittest.TestCase):
    def test_a3_fixed_size_source_fixture(self):
        self.assertEqual([p.hex() for p in a3_packets(b"\x5d\x01")], [
            "a3000102585d01000000000000000000000000a4",
            "a3ff00000000000000000000000000000000005c",
        ])
        packets = a3_packets(bytes(range(32)))
        self.assertEqual(packets[0][:5], bytes.fromhex("a300010358"))
        self.assertEqual(packets[1][:2], bytes.fromhex("a301"))
        self.assertEqual(packets[2][:3], bytes.fromhex("a3ff1f"))
        self.assertTrue(all(len(p) == 20 for p in packets))

    def test_small_packet_app_fixture(self):
        # App's special short-transfer branch still sends an empty FFFF end.
        self.assertEqual([p.hex() for p in mtu_packets(b"\x5d\x01", 20)],
                         ["a40000010200585d01a3", "a4ffffa4"])

    def test_exact_first_boundary_and_multi_packet_fixture(self):
        self.assertEqual(len(mtu_packets(bytes(12), 20)), 2)
        self.assertEqual([p.hex() for p in mtu_packets(bytes(range(30)), 20)], [
            "a4000001030058000102030405060708090a0bfe",
            "a401000c0d0e0f101112131415161718191a1ba5",
            "a4ffff1c1da5",
        ])

    def test_single_png_layer_can_be_decoded(self):
        encoded = png_frame(Image.new("RGB", (32, 32), (0, 255, 0)))
        self.assertEqual(encoded[:8], bytes.fromhex("5e00000064000001"))
        record_size = int.from_bytes(encoded[8:10], "little")
        self.assertEqual(len(encoded), 10 + record_size + 1)
        self.assertEqual(encoded[10], 0)
        png_size = int.from_bytes(encoded[11:13], "little")
        with Image.open(io.BytesIO(encoded[13:13 + png_size])) as image:
            self.assertEqual(image.size, (32, 32))
            self.assertEqual(image.getpixel((31, 31)), (0, 255, 0))
        self.assertEqual(encoded[13 + png_size:], bytes.fromhex("003264016400000000"))

    def test_ack_result_and_integrity(self):
        self.assertEqual(mtu_acknowledgement(bytes.fromhex("a458" + "00" * 17 + "fc")), 0)
        self.assertEqual(mtu_acknowledgement(bytes.fromhex("a45801" + "00" * 16 + "fd")), 1)
        self.assertIsNone(mtu_acknowledgement(b"\x33\x05\x00"))
        with self.assertRaises(ValueError):
            mtu_acknowledgement(b"\xa4\x58" + bytes(18))

    def test_wrong_frame_and_unavailable_mtu_rejected(self):
        with self.assertRaises(ValueError):
            png_frame(Image.new("RGB", (52, 32)))
        for invalid in (19, 513):
            with self.assertRaises(ValueError):
                mtu_packets(b"x", invalid)


if __name__ == "__main__":
    unittest.main()
