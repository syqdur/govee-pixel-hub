"""Tests for pixel font rendering and character coverage."""
import unittest
from PIL import Image
import pixel_font


class PixelFontTests(unittest.TestCase):
    def test_umlauts_and_eszett_render(self):
        text = "Ärger über große Ölfelder"
        width = pixel_font.measure_text(text, font_type="normal")
        self.assertGreater(width, 50)
        img, w = pixel_font.create_text_strip([(text, "#ffffff")], height=9)
        self.assertEqual(width, w)
        self.assertEqual(img.size, (w, 9))

    def test_symbols_and_numbers(self):
        text = "Track 01 · 100% ♪ ♥"
        width = pixel_font.measure_text(text, font_type="normal")
        img, w = pixel_font.create_text_strip([(text, "#1ed760")], height=9)
        self.assertEqual(width, w)
        # Verify some pixels were actually drawn
        has_pixels = any(img.getpixel((x, y))[1] > 0 for x in range(w) for y in range(9))
        self.assertTrue(has_pixels)

    def test_clock_font_digits(self):
        for digit in "0123456789:":
            w = pixel_font.measure_text(digit, font_type="clock")
            self.assertGreater(w, 0)
        time_w = pixel_font.measure_text("14:35", font_type="clock")
        self.assertLessEqual(time_w, 30)

    def test_mini_font(self):
        for ch in "0123456789+:-.":
            w = pixel_font.measure_text(ch, font_type="mini")
            self.assertGreater(w, 0)

    def test_substitutions_fallback(self):
        text = "Café naïve"
        w = pixel_font.measure_text(text, font_type="normal")
        self.assertGreater(w, 20)


if __name__ == "__main__":
    unittest.main()
