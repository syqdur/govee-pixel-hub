"""Protocol fixtures and image compatibility checks for the H6630 uploader."""
import base64
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from pixel_upload import acknowledgement, gif_bytes, link_command


class PixelProtocolTests(unittest.TestCase):
    def test_device_success_and_rejection_fixtures(self):
        # Actual H6630 replies: GIF87a was rejected; GIF89a was accepted.
        fixture = {"device": "own-display", "cmd": "ptUrl", "transaction": "test",
                   "op": {"command": ["MwUAAAAAAAAAAAAAAAAAAAAAADY="]}}
        self.assertEqual(acknowledgement(fixture, "test", "own-display"), 0)
        fixture["op"]["command"] = ["MwUBAAAAAAAAAAAAAAAAAAAAADc="]
        self.assertEqual(acknowledgement(fixture, "test", "own-display"), 1)
        self.assertIsNone(acknowledgement(fixture, "other", "own-display"))
        self.assertIsNone(acknowledgement(fixture, "test", "other-display"))

    def test_incomplete_reply_is_not_success(self):
        with self.assertRaises(RuntimeError):
            acknowledgement({"device": "d", "cmd": "ptUrl", "transaction": "t"}, "t", "d")

    def test_static_gif87a_becomes_device_compatible_gif89a(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "blue.gif"
            Image.new("RGB", (32, 32), "blue").save(path)
            self.assertTrue(path.read_bytes().startswith(b"GIF87a"))
            converted = gif_bytes(path)
            self.assertTrue(converted.startswith(b"GIF89a"))
            path.write_bytes(converted)
            with Image.open(path) as image:
                self.assertEqual(image.convert("RGB").getpixel((0, 0)), (0, 0, 255))
                self.assertEqual(image.info["loop"], 0)

    def test_wrong_resolution_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wrong.png"
            Image.new("RGB", (52, 32)).save(path)
            with self.assertRaises(ValueError):
                gif_bytes(path)

    def test_url_protocol_matches_app_field_order(self):
        link = "https://example.com/gif"
        command = link_command(link, 1, 100)
        self.assertEqual(command[:6].hex(), "fd003c001700")
        self.assertEqual(command[6:].decode(), link)
        with self.assertRaises(ValueError):
            link_command("http://example.com/gif", 1, 100)


if __name__ == "__main__":
    unittest.main()
