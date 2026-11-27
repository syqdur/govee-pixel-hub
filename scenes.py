"""Render display scenes as looping 32x32 GIFs with device-side animation.

Provides high-readability pixel art layouts:
- spotify_scene: 20x20 album cover (or vinyl fallback), dynamic spectrum equalizer,
  playback progress bar, mini-clock or unread badge, and smooth marquee with full
  German umlaut and symbol support.
- discord_scene: Discord blurple banner, attention pulse, sender & message marquee.
- idle_scene: Glowing 5x7 retro digital clock with pulsing colon, day of week,
  date, and Discord unread badge.
"""
import datetime
import io
import time

import math
from PIL import Image, ImageDraw, ImageOps

import pixel_font

GREEN = "#1ed760"
LIME = "#76ff03"
YELLOW = "#ffeb3b"
CORAL = "#ff5252"
BLURPLE = "#5865F2"
WHITE = "#ffffff"
GREY = "#9a9a9a"
DIM = "#222222"
CYAN = "#00e5ff"
LAVENDER = "#c9cdfb"
AMBER = "#ffb300"

STEP_MS, HOLD_MS, GAP = 85, 1400, 16
EQ_EVERY = 4

# Discord-style controller face, 11x8.
DISCORD_ICON = [
    "..XXX.XXX..",
    ".XXXXXXXXX.",
    "XXXXXXXXXXX",
    "XXX..X..XXX",
    "XXX..X..XXX",
    "XXXXXXXXXXX",
    "XXXX...XXXX",
    ".XX.....XX.",
]

# Rhythmic equalizer bar heights per phase (3 bars)
EQ_PATTERNS = [
    (3, 6, 4),
    (5, 7, 3),
    (7, 4, 6),
    (4, 8, 5),
    (6, 3, 7),
    (3, 5, 4),
    (5, 8, 2),
    (7, 6, 5),
]

GERMAN_DAYS = ["MO", "DI", "MI", "DO", "FR", "SA", "SO"]


class Marquee:
    """Seamless horizontal scroll of a text strip inside a box of `box` pixels."""

    def __init__(self, parts, box=32, font_type="normal", y_offset=None):
        if y_offset is None:
            y_offset = 2 if font_type == "mini" else 1
        self.image, self.width = pixel_font.create_text_strip(
            parts, height=9, font_type=font_type, spacing=1, y_offset=y_offset
        )
        self.box = box
        self.cycle = self.width + GAP if self.width > box - 1 else 0

    def paste(self, target, x, y, step):
        if not self.cycle:
            target.paste(self.image, (x + (self.box - self.width) // 2, y))
            return
        offset = step % self.cycle
        window = Image.new("RGB", (self.box, self.image.height), "black")
        window.paste(self.image, (1 - offset, 0))
        window.paste(self.image, (1 - offset + self.cycle, 0))
        target.paste(window, (x, y))


def _badge(draw, x, y, count):
    """8x8 or 9x9 blurple badge with unread count."""
    label = str(count) if count < 10 else "+"
    draw.rounded_rectangle((x, y, x + 8, y + 8), 2, fill=BLURPLE)
    pixel_font.draw_text(draw._image, (x + 3, y + 2), label, fill=WHITE, font_type="mini")


def _lzw(indices, bits):
    """GIF LZW compression of palette indices with minimum code size `bits`."""
    clear, stop = 1 << bits, (1 << bits) + 1
    table = {bytes([i]): i for i in range(clear)}
    size, next_code = bits + 1, stop + 1
    out, acc, nbits = bytearray(), 0, 0

    def emit(code):
        nonlocal acc, nbits
        acc |= code << nbits
        nbits += size
        while nbits >= 8:
            out.append(acc & 255)
            acc >>= 8
            nbits -= 8

    emit(clear)
    word = b""
    for value in indices:
        candidate = word + bytes([value])
        if candidate in table:
            word = candidate
            continue
        emit(table[word])
        if next_code < 4096:
            table[candidate] = next_code
            next_code += 1
            if next_code > (1 << size) and size < 12:
                size += 1
        else:
            emit(clear)
            table = {bytes([i]): i for i in range(clear)}
            size, next_code = bits + 1, stop + 1
        word = bytes([value])
    if word:
        emit(table[word])
    emit(stop)
    if nbits:
        out.append(acc & 255)
    return bytes(out)


def _encode(frames, durations):
    """GIF89a with ONE global palette and changed-rectangle frames (no local palettes)."""
    # Sample frames across the animation for an accurate global palette
    sample_indices = [
        int(i * (len(frames) - 1) / max(1, min(12, len(frames)) - 1))
        for i in range(min(12, len(frames)))
    ]
    source = Image.new("RGB", (32, 32 * len(sample_indices)))
    for pos, idx in enumerate(sample_indices):
        source.paste(frames[idx], (0, 32 * pos))
    palette = source.quantize(colors=128, method=Image.Quantize.MEDIANCUT)
    indexed = [f.quantize(palette=palette, dither=Image.Dither.NONE).tobytes() for f in frames]
    colours = palette.getpalette()[: 128 * 3]
    colours += [0] * (128 * 3 - len(colours))
    gif = bytearray(b"GIF89a" + (32).to_bytes(2, "little") * 2 + bytes([0xF6, 0, 0]))
    gif += bytes(colours)
    gif += b"\x21\xff\x0b" + b"NETSCAPE2.0" + b"\x03\x01\x00\x00\x00"  # loop forever
    previous = None
    for pixels, duration in zip(indexed, durations):
        if previous is None:
            x0, y0, x1, y1 = 0, 0, 32, 32
        else:
            changed = [i for i in range(1024) if pixels[i] != previous[i]]
            if not changed:
                changed = [0]
            xs, ys = [i % 32 for i in changed], [i // 32 for i in changed]
            x0, y0, x1, y1 = min(xs), min(ys), max(xs) + 1, max(ys) + 1
        delay = max(2, round(duration / 10))
        gif += b"\x21\xf9\x04\x04" + delay.to_bytes(2, "little") + b"\x00\x00"
        gif += b"\x2c" + b"".join(v.to_bytes(2, "little") for v in (x0, y0, x1 - x0, y1 - y0)) + b"\x00"
        region = bytes(pixels[y * 32 + x] for y in range(y0, y1) for x in range(x0, x1))
        data = _lzw(region, 7)
        gif += b"\x07"
        for i in range(0, len(data), 255):
            chunk = data[i : i + 255]
            gif += bytes([len(chunk)]) + chunk
        gif += b"\x00"
        previous = pixels
    gif += b"\x3b"
    return bytes(gif)


def _cover(thumbnail, size=20):
    """Scales album cover or creates a stylish vinyl record fallback."""
    if not thumbnail:
        # Vinyl disc fallback
        im = Image.new("RGB", (size, size), "#0d0d0d")
        d = ImageDraw.Draw(im)
        d.ellipse((1, 1, size - 2, size - 2), fill="#1a1a1a", outline="#333333")
        d.ellipse((4, 4, size - 5, size - 5), outline="#262626")
        d.ellipse((7, 7, size - 8, size - 8), fill=GREEN)
        d.ellipse((9, 9, size - 10, size - 10), fill="#000000")
        d.point((4, 5), fill="#444444")
        d.point((14, 15), fill="#444444")
        return im
    with Image.open(io.BytesIO(thumbnail)) as original:
        return ImageOps.fit(original.convert("RGB"), (size, size), method=Image.Resampling.LANCZOS)


def generate_fluid_eq_sequence(total_frames, playing=True):
    """Generates a gentle, organic 5-bar equalizer sequence with floating-point heights for sub-pixel anti-aliasing."""
    if not playing or total_frames <= 0:
        return [(1.0, 1.0, 1.0, 1.0, 1.0)] * max(1, total_frames)

    # Calm, gentle musical waves (2-3 gentle oscillations per loop)
    cycles = max(2, round(total_frames / 16.0))
    configs = [
        # (mult1, mult2, phase, min_h, max_h)
        (cycles, cycles * 2, 0.0, 1.2, 5.8),         # Sub-bass: slow breathing pulse
        (cycles, cycles + 1, 1.8, 1.5, 6.2),         # Bass: gentle groove
        (cycles * 2, cycles, 3.2, 1.2, 6.5),         # Mid: smooth center peak
        (cycles + 1, cycles * 2, 0.9, 1.5, 6.0),     # High-Mid: soft sway
        (cycles * 2, cycles + 1, 2.5, 1.0, 5.2),     # Treble: delicate shimmer
    ]

    raw = []
    for k in range(total_frames):
        t = 2.0 * math.pi * k / total_frames
        heights = []
        for f1, f2, ph, min_h, max_h in configs:
            wave = 0.70 * math.sin(f1 * t + ph) + 0.30 * math.sin(f2 * t + ph * 1.2)
            norm = (wave + 1.0) / 2.0
            # S-curve ease for soft start and soft deceleration
            eased = norm * norm * (3.0 - 2.0 * norm)
            h = min_h + eased * (max_h - min_h)
            heights.append(round(h, 2))
        raw.append(heights)

    # Soft low-pass smoothing across cyclic frames to ensure buttery gentle slope
    smoothed = [list(h) for h in raw]
    for _ in range(2):
        for k in range(total_frames):
            prev = smoothed[(k - 1) % total_frames]
            curr = smoothed[k]
            nxt = smoothed[(k + 1) % total_frames]
            for b in range(5):
                curr[b] = round(0.25 * prev[b] + 0.50 * curr[b] + 0.25 * nxt[b], 2)

    return [tuple(h) for h in smoothed]


def _get_cover_colors(cover_image):
    """Extracts dominant vibrant color and highlight from the album cover."""
    small = cover_image.resize((16, 16), Image.Resampling.BOX)
    colors = small.getcolors(maxcolors=256) or []
    vibrant = []
    for count, rgb in colors:
        r, g, b = rgb[:3]
        brightness = (r + g + b) / 3
        saturation = max(r, g, b) - min(r, g, b)
        if brightness > 30 and saturation > 20:
            vibrant.append((saturation * count, (r, g, b)))
    vibrant.sort(reverse=True)
    if vibrant:
        best = vibrant[0][1]
        accent = vibrant[1][1] if len(vibrant) > 1 else (min(255, best[0] + 50), min(255, best[1] + 50), min(255, best[2] + 50))
        return best, accent
    return ((30, 215, 96), (118, 255, 3))


def _boost_accent(color):
    """Ensures minimum luminance for high-contrast legible text on black display."""
    r, g, b = color
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    if lum < 130:
        boost = 130 / max(1.0, lum)
        return (min(255, int(r * boost)), min(255, int(g * boost)), min(255, int(b * boost)))
    return (r, g, b)


def _normalize_glow_color(rgb):
    """Ensures vibrant, visible ambient aura colors even from very dark or muted album art."""
    r, g, b = rgb
    peak = max(r, g, b)
    if peak < 160:
        boost = 180.0 / max(1, peak)
        r, g, b = min(255, int(r * boost)), min(255, int(g * boost)), min(255, int(b * boost))
    # If monochrome / grayscale, provide a stylish ambient cyan/blue tint
    spread = max(r, g, b) - min(r, g, b)
    if spread < 18:
        return (60, 140, 220)
    return (r, g, b)


def _draw_ambient_glow(image, color, pulse=1.0, cover_box=(6, 1, 25, 20)):
    """Draws a rich atmospheric ambient aura bleeding out from the album cover with gentle breathing."""
    x0, y0, x1, y1 = cover_box
    cr, cg, cb = _normalize_glow_color(color)
    # Quantize breathing pulse into smooth distinct stages to keep GIF payload compact
    p_step = round(pulse * 3) / 3.0
    intensity = 0.60 + 0.40 * p_step  # breathes gently between 60% and 100% (never turns off)
    for gy in range(22):
        for gx in range(32):
            dx = (x0 - gx) if gx < x0 else ((gx - x1) if gx > x1 else 0)
            dy = (y0 - gy) if gy < y0 else ((gy - y1) if gy > y1 else 0)
            dist = math.hypot(dx, dy)
            factor = max(0.0, 0.32 - dist * 0.040) * intensity
            if factor > 0.02:
                image.putpixel((gx, gy), (int(cr * factor), int(cg * factor), int(cb * factor)))


def _draw_cover_eq(image, heights, colors, playing=True):
    """Draws 5 equalizer bars overlaid symmetrically at rows 14..20 with sub-pixel fractional dimming (anti-aliasing)."""
    c_base, c_accent = colors
    draw = ImageDraw.Draw(image)

    # Tinted glass backdrop: centered across x=8..23, y=13..20 (2px margin to cover edges 6 and 25)
    for gy in range(13, 21):
        for gx in range(8, 24):
            r, g, b = image.getpixel((gx, gy))
            image.putpixel((gx, gy), (r // 3, g // 3, b // 3))

    # 5 bars symmetrically centered: x=9..10, 12..13, 15..16 (exact matrix center), 18..19, 21..22
    bar_xs = (9, 12, 15, 18, 21)
    for bx, h in zip(bar_xs, heights):
        full_h = int(h)
        frac = h - full_h

        # Solid body rows
        top_full_y = max(14, 20 - full_h + 1)
        for y in range(top_full_y, 21):
            c = c_accent if (y == top_full_y and frac < 0.2) else c_base
            draw.point((bx, y), fill=c)
            draw.point((bx + 1, y), fill=c)

        # Fractional top row: sub-pixel anti-aliasing / andimmen for flowing liquid motion
        frac_y = 20 - full_h
        if frac > 0.05 and frac_y >= 14:
            for x in (bx, bx + 1):
                bg_r, bg_g, bg_b = image.getpixel((x, frac_y))
                dim_r = int(bg_r + (c_accent[0] - bg_r) * frac)
                dim_g = int(bg_g + (c_accent[1] - bg_g) * frac)
                dim_b = int(bg_b + (c_accent[2] - bg_b) * frac)
                image.putpixel((x, frac_y), (dim_r, dim_g, dim_b))


def _draw_weather_icon(image, icon_type, frame_idx=0, offset=(9, 1)):
    """Draws a 14x14 animated pixel weather icon."""
    draw = ImageDraw.Draw(image)
    ox, oy = offset
    gold = "#ffb300"
    yellow = "#ffee58"
    amber = "#ff8f00"
    white = "#ffffff"
    cyan = "#00e5ff"
    blue = "#29b6f6"

    if icon_type in ("sun", "clear_day"):
        draw.rectangle((ox + 4, oy + 4, ox + 8, oy + 8), fill=gold)
        draw.point((ox + 5, oy + 5), fill=yellow)
        draw.point((ox + 7, oy + 5), fill=yellow)
        draw.point((ox + 6, oy + 7), fill=yellow)
        phase = frame_idx % 4
        c1 = yellow if phase in (0, 2) else amber
        c2 = yellow if phase in (1, 3) else amber
        draw.line((ox + 5, oy + 1, ox + 7, oy + 1), fill=c1)
        draw.line((ox + 5, oy + 11, ox + 7, oy + 11), fill=c1)
        draw.line((ox + 1, oy + 5, ox + 1, oy + 7), fill=c1)
        draw.line((ox + 11, oy + 5, ox + 11, oy + 7), fill=c1)
        draw.point((ox + 2, oy + 2), fill=c2)
        draw.point((ox + 10, oy + 2), fill=c2)
        draw.point((ox + 2, oy + 10), fill=c2)
        draw.point((ox + 10, oy + 10), fill=c2)

    elif icon_type in ("moon", "clear_night"):
        moon_pixels = [
            (5, 2), (6, 2), (7, 2),
            (4, 3), (5, 3),
            (3, 4), (4, 4),
            (3, 5), (4, 5),
            (3, 6), (4, 6),
            (3, 7), (4, 7),
            (4, 8), (5, 8),
            (5, 9), (6, 9), (7, 9),
        ]
        for mx, my in moon_pixels:
            draw.point((ox + mx, oy + my), fill=white)
        draw.point((ox + 4, oy + 5), fill="#b2ebf2")
        draw.point((ox + 4, oy + 6), fill="#b2ebf2")
        phase = frame_idx % 3
        if phase != 0:
            draw.point((ox + 9, oy + 3), fill=yellow)
        if phase != 1:
            draw.point((ox + 10, oy + 8), fill=white)
        if phase != 2:
            draw.point((ox + 2, oy + 9), fill=cyan)

    elif icon_type in ("cloud", "fog"):
        draw.rectangle((ox + 2, oy + 5, ox + 11, oy + 8), fill=white)
        draw.rectangle((ox + 4, oy + 3, ox + 8, oy + 5), fill=white)
        draw.line((ox + 2, oy + 8, ox + 11, oy + 8), fill="#546e7a")
        draw.line((ox + 2, oy + 7, ox + 11, oy + 7), fill="#90a4ae")
        if icon_type == "fog":
            draw.line((ox + 1, oy + 10, ox + 12, oy + 10), fill="#90a4ae")
            draw.line((ox + 3, oy + 12, ox + 10, oy + 12), fill="#78909c")

    elif icon_type == "partly_cloudy":
        draw.rectangle((ox + 8, oy + 1, ox + 11, oy + 4), fill=gold)
        draw.point((ox + 9, oy + 2), fill=yellow)
        draw.point((ox + 12, oy + 1), fill=yellow)
        draw.rectangle((ox + 1, oy + 4, ox + 10, oy + 7), fill=white)
        draw.rectangle((ox + 3, oy + 2, ox + 7, oy + 4), fill=white)
        draw.line((ox + 1, oy + 7, ox + 10, oy + 7), fill="#78909c")
        draw.line((ox + 1, oy + 6, ox + 10, oy + 6), fill="#b0bec5")

    elif icon_type == "rain":
        draw.rectangle((ox + 2, oy + 2, ox + 11, oy + 5), fill="#90a4ae")
        draw.rectangle((ox + 4, oy + 1, ox + 8, oy + 2), fill="#cfd8dc")
        draw.line((ox + 2, oy + 5, ox + 11, oy + 5), fill="#546e7a")
        p = frame_idx % 4
        y1 = oy + 7 + (p % 3)
        if y1 <= oy + 10:
            draw.point((ox + 3, y1), fill=blue)
        y2 = oy + 7 + ((p + 1) % 3)
        if y2 <= oy + 10:
            draw.point((ox + 6, y2), fill=blue)
        y3 = oy + 7 + ((p + 2) % 3)
        if y3 <= oy + 10:
            draw.point((ox + 9, y3), fill=blue)

    elif icon_type == "thunder":
        draw.rectangle((ox + 2, oy + 1, ox + 11, oy + 4), fill="#455a64")
        draw.rectangle((ox + 4, oy + 0, ox + 8, oy + 1), fill="#78909c")
        if (frame_idx % 4) in (1, 2):
            ylw = "#ffea00"
            draw.line((ox + 6, oy + 5, ox + 8, oy + 7), fill=ylw)
            draw.line((ox + 5, oy + 8, ox + 7, oy + 8), fill=ylw)
            draw.line((ox + 6, oy + 9, ox + 8, oy + 11), fill=ylw)

    elif icon_type == "snow":
        draw.rectangle((ox + 2, oy + 2, ox + 11, oy + 5), fill="#90a4ae")
        draw.rectangle((ox + 4, oy + 1, ox + 8, oy + 2), fill="#eceff1")
        p = frame_idx % 4
        if p in (0, 2):
            draw.point((ox + 4, oy + 7), fill=white)
            draw.point((ox + 8, oy + 9), fill=white)
        else:
            draw.point((ox + 4, oy + 8), fill=white)
            draw.point((ox + 8, oy + 10), fill=white)
            draw.point((ox + 6, oy + 7), fill=white)


def _draw_mini_weather(image, icon_type, ox=27, oy=2):
    """Draws a compact 5x5 weather glyph on Spotify's side margin."""
    draw = ImageDraw.Draw(image)
    if icon_type in ("sun", "clear_day"):
        draw.rectangle((ox + 1, oy + 1, ox + 3, oy + 3), fill="#ffffff")
        draw.point((ox + 2, oy), fill="#ffffff")
        draw.point((ox + 2, oy + 4), fill="#ffffff")
        draw.point((ox, oy + 2), fill="#ffffff")
        draw.point((ox + 4, oy + 2), fill="#ffffff")
    elif icon_type in ("moon", "clear_night"):
        draw.point((ox + 2, oy), fill="#ffffff")
        draw.point((ox + 1, oy + 1), fill="#ffffff")
        draw.point((ox + 1, oy + 2), fill="#ffffff")
        draw.point((ox + 1, oy + 3), fill="#ffffff")
        draw.point((ox + 2, oy + 4), fill="#ffffff")
    elif icon_type in ("rain", "thunder"):
        draw.rectangle((ox, oy + 1, ox + 4, oy + 2), fill="#b0bec5")
        draw.point((ox + 1, oy + 4), fill="#ffffff")
        draw.point((ox + 3, oy + 4), fill="#ffffff")
    elif icon_type == "snow":
        draw.rectangle((ox, oy + 1, ox + 4, oy + 2), fill="#b0bec5")
        draw.point((ox + 1, oy + 4), fill="#ffffff")
        draw.point((ox + 3, oy + 4), fill="#ffffff")
    else:
        draw.rectangle((ox, oy + 1, ox + 4, oy + 3), fill="#ffffff")
        draw.point((ox + 1, oy), fill="#ffffff")
        draw.point((ox + 2, oy), fill="#ffffff")
        draw.line((ox, oy + 3, ox + 4, oy + 3), fill="#78909c")


def _rounded_cover_mask(size=20):
    """Builds a soft anti-aliased corner mask so the 20x20 cover looks optically rounded on LEDs."""
    mask = Image.new("L", (size, size), 255)
    m = size - 1
    for cx, cy in ((0, 0), (m, 0), (0, m), (m, m)):
        mask.putpixel((cx, cy), 0)
    for cx, cy in ((1, 0), (0, 1), (m - 1, 0), (m, 1), (0, m - 1), (1, m), (m - 1, m), (m, m - 1)):
        mask.putpixel((cx, cy), 115)
    return mask


_COVER_MASK_20 = _rounded_cover_mask(20)


def _draw_spotify_top_bar(image, weather=None, show_weather=True, show_clock=False, hour_str="", min_str="", clock_color=WHITE):
    """Draws a 70%-transparent dark top bar restricted to the 20px album cover width (x=6..25, y=1..7)."""
    if not ((weather and show_weather) or show_clock):
        return

    # 70% dark transparency across the album cover top edge (x=6..25, y=1..7)
    for gy in range(1, 8):
        for gx in range(6, 26):
            r, g, b = image.getpixel((gx, gy))
            image.putpixel((gx, gy), (int(r * 0.30), int(g * 0.30), int(b * 0.30)))

    # Measure weather block horizontally: [5x5 icon] + 2px gap + [2px '-' if neg] + [abs(temp)°]
    w_weather_total = 0
    w_temp = weather.get("temp") if (weather and show_weather) else None
    temp_abs_str = f"{abs(w_temp)}°" if w_temp is not None else ""
    is_neg = (w_temp is not None and w_temp < 0)
    if weather and show_weather:
        w_weather_total = 5
        if w_temp is not None:
            w_num = pixel_font.measure_text(temp_abs_str, font_type="mini", spacing=1)
            w_weather_total += 2 + (3 if is_neg else 0) + w_num

    if show_clock:
        time_lbl = f"{hour_str}:{min_str}"
        pixel_font.draw_text(image, (1, 2), time_lbl, fill=clock_color, font_type="mini", spacing=1)

    if weather and show_weather:
        wx = 6 + max(0, (20 - w_weather_total) // 2)
        _draw_mini_weather(image, weather.get("icon", "sun"), ox=wx, oy=2)
        if w_temp is not None:
            tx = wx + 7
            if is_neg:
                image.putpixel((tx, 4), (255, 255, 255))
                image.putpixel((tx + 1, 4), (255, 255, 255))
                tx += 3
            pixel_font.draw_text(image, (tx, 2), temp_abs_str, fill=WHITE, font_type="mini", spacing=1)


def spotify_scene(track, thumbnail, unread=0, playing=True, timeline=None, options=None, weather=None, now_dt=None):
    """Album art centered at (6, 1), progress bar at row 22, scrolling title below, optional clock & weather."""
    opts = options or {}
    step_ms = int(opts.get("text_speed_ms", STEP_MS))
    hold_ms = int(opts.get("text_hold_ms", HOLD_MS))
    show_weather = opts.get("spotify_show_weather", True)
    show_clock = opts.get("spotify_mini_clock", True)
    show_eq = opts.get("spotify_eq", False)
    clock_color = opts.get("clock_color", WHITE)

    now = now_dt or datetime.datetime.now()
    hour_str = now.strftime("%H")
    min_str = now.strftime("%M")

    cover = _cover(thumbnail, 20)
    c_base, c_accent = _get_cover_colors(cover)
    c_accent_boosted = _boost_accent(c_accent)

    if not playing:
        cover = Image.blend(cover, Image.new("RGB", cover.size, "black"), 0.55)
        # Clean pause symbol centered on the dimmed cover
        d_cov = ImageDraw.Draw(cover)
        d_cov.rectangle((7, 6, 9, 13), fill=WHITE)
        d_cov.rectangle((11, 6, 13, 13), fill=WHITE)

    title = track.get("title", "Unknown")
    artist = track.get("artist", "")

    font_mini = opts.get("spotify_font_mini", False) or (opts.get("spotify_font_size") == "mini")
    font_type = "mini" if font_mini else "normal"
    text_mode = opts.get("spotify_text_mode", "marquee")

    if text_mode == "pages":
        # Ultra-compact 2 to 3-frame Page Mode (< 900 bytes, ~0.08s upload time)
        # Prevents any Bluetooth A2DP audio dropouts / interference on AirPods!
        base = Image.new("RGB", (32, 32), "black")
        _draw_ambient_glow(base, c_base, pulse=1.0)
        base.paste(cover, (6, 1), _COVER_MASK_20)
        draw_b = ImageDraw.Draw(base)

        _draw_spotify_top_bar(
            base, weather=weather, show_weather=show_weather,
            show_clock=show_clock, hour_str=hour_str, min_str=min_str, clock_color=clock_color,
        )

        # Subtle elegant divider line tinted with album aura
        c_norm = _normalize_glow_color(c_base)
        c_div = (max(25, int(c_norm[0] * 0.35)), max(25, int(c_norm[1] * 0.35)), max(25, int(c_norm[2] * 0.35)))
        draw_b.line((2, 22, 29, 22), fill=c_div)
        draw_b.point((15, 22), fill=WHITE)
        draw_b.point((16, 22), fill=WHITE)

        frames, durations = [], []
        t_w = pixel_font.measure_text(title, font_type=font_type, spacing=1)

        # Title Page(s)
        if t_w <= 30:
            f_title = base.copy()
            tx = max(1, (32 - t_w) // 2)
            pixel_font.draw_text(f_title, (tx, 25), title, fill=WHITE, font_type=font_type, spacing=1)
            frames.append(f_title)
            durations.append(3500)
        else:
            f1 = base.copy()
            pixel_font.draw_text(f1, (1, 25), title, fill=WHITE, font_type=font_type, spacing=1)
            frames.append(f1)
            durations.append(3000)

            f2 = base.copy()
            pixel_font.draw_text(f2, (31 - t_w, 25), title, fill=WHITE, font_type=font_type, spacing=1)
            frames.append(f2)
            durations.append(3000)

        # Artist Page with white dot separator
        if artist:
            f_art = base.copy()
            art_parts = [("· ", WHITE), (artist, c_accent_boosted)]
            strip, full_a_w = pixel_font.create_text_strip(art_parts, height=9, font_type=font_type, spacing=1, y_offset=2)
            ax = max(1, (32 - full_a_w) // 2) if full_a_w <= 30 else 1
            f_art.paste(strip, (ax, 23))
            frames.append(f_art)
            durations.append(3500)

        return _encode(frames, durations)

    parts = [(title, WHITE)]
    if artist:
        parts.extend([(" · ", WHITE), (artist, c_accent_boosted)])

    text = Marquee(parts, box=32, font_type=font_type)

    if text.cycle == 0:
        step_px = 1
        steps = 1
    else:
        # Smooth 1-pixel continuous glide (~10-25 FPS depending on text_speed_ms)
        step_px = 1
        steps = text.cycle

    frame_dur = max(40, step_ms)

    # Pre-generate gentle cyclic EQ heights with sub-pixel floats if EQ enabled
    eq_sequence = generate_fluid_eq_sequence(steps, playing=playing) if show_eq else None

    ambient_breath = opts.get("spotify_ambient_breath", False)

    frames, durations = [], []
    for step in range(steps):
        image = Image.new("RGB", (32, 32), "black")
        # Soft atmospheric ambient glow bleeding out from the album cover (with gentle breathing)
        if ambient_breath and steps > 1:
            t = 2.0 * math.pi * step / steps
            pulse = 0.50 + 0.50 * math.sin(t)
        else:
            pulse = 1.0
        _draw_ambient_glow(image, c_base, pulse=pulse)
        # Center album art 20x20 at x=6, y=1 with soft rounded LED corners
        image.paste(cover, (6, 1), _COVER_MASK_20)
        draw = ImageDraw.Draw(image)

        # Equalizer overlay on album cover (only if explicitly enabled)
        if show_eq and eq_sequence:
            _draw_cover_eq(image, eq_sequence[step], (c_base, c_accent), playing=playing)

        # Translucent 70% dark top bar with horizontal weather & optional clock
        _draw_spotify_top_bar(
            image, weather=weather, show_weather=show_weather,
            show_clock=show_clock, hour_str=hour_str, min_str=min_str, clock_color=clock_color,
        )

        # Divider / Progress Bar at row 22 (x=1..30)
        sync_sec = opts.get("progress_sync_seconds", 0)
        if timeline and timeline[1] > 0 and sync_sec > 0:
            start_pos, end = timeline
            pct = max(0.0, min(1.0, start_pos / end))
            fill_w = int(round(pct * 30))
            if fill_w > 0:
                draw.line((1, 22, fill_w, 22), fill=GREEN)
                draw.point((fill_w, 22), fill=WHITE)  # glowing progress head
            else:
                draw.point((1, 22), fill=WHITE)
            if fill_w < 30:
                draw.line((max(1, fill_w + 1), 22, 30, 22), fill=DIM)
        else:
            # Subtle elegant divider line tinted with album aura
            c_norm = _normalize_glow_color(c_base)
            c_div = (max(25, int(c_norm[0] * 0.35)), max(25, int(c_norm[1] * 0.35)), max(25, int(c_norm[2] * 0.35)))
            draw.line((2, 22, 29, 22), fill=c_div)
            draw.point((15, 22), fill=WHITE)
            draw.point((16, 22), fill=WHITE)

        # Marquee text at rows 23..31: seamless continuous flow with 0 jump
        text.paste(image, 0, 23, step * step_px)
        frames.append(image)
        # Hold frame 0 briefly so the title start is easy to read
        dur = (frame_dur + hold_ms) if (step == 0 and hold_ms > 0 and steps > 1) else frame_dur
        durations.append(dur)

    return _encode(frames, durations)


def discord_scene(sender, message, options=None):
    """Blurple header with Discord icon, sender & message marquee with attention pulse."""
    top = Marquee([(sender, WHITE)])
    bottom = Marquee([(message, LAVENDER)])
    raw_steps = max(top.cycle, bottom.cycle, 1)
    step_px = 2 if raw_steps > 1 else 1
    steps = max(1, (raw_steps + step_px - 1) // step_px)

    frames, durations = [], []

    # Optional attention pulse
    pulse = Image.new("RGB", (32, 32), "black")
    d_pulse = ImageDraw.Draw(pulse)
    d_pulse.rectangle((0, 0, 31, 10), fill="#7289da")
    for y, row in enumerate(DISCORD_ICON):
        for x, c in enumerate(row):
            if c == "X":
                d_pulse.point((10 + x, 1 + y), fill=WHITE)
    top.paste(pulse, 0, 12, 0)
    bottom.paste(pulse, 0, 22, 0)
    frames.append(pulse)
    durations.append(180)

    for s_idx in range(steps):
        px = s_idx * step_px
        image = Image.new("RGB", (32, 32), "black")
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 31, 10), fill=BLURPLE)
        for y, row in enumerate(DISCORD_ICON):
            for x, c in enumerate(row):
                if c == "X":
                    draw.point((10 + x, 1 + y), fill=WHITE)
        top.paste(image, 0, 12, px)
        bottom.paste(image, 0, 22, px)
        frames.append(image)
        durations.append(HOLD_MS if s_idx == 0 and steps > 1 else 160)

    return _encode(frames, durations), sum(durations) / 1000


def _lerp_color(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


def _gradient_sample(stops, t):
    """Samples a multi-stop RGB gradient at t in [0.0, 1.0]."""
    t = max(0.0, min(1.0, t))
    if len(stops) == 1:
        return stops[0]
    scaled = t * (len(stops) - 1)
    idx = min(int(scaled), len(stops) - 2)
    return _lerp_color(stops[idx], stops[idx + 1], scaled - idx)


def _hex_to_rgb(hex_str, fallback=(0, 229, 255)):
    s = str(hex_str or "").strip().lstrip("#")
    if len(s) == 6:
        try:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
        except ValueError:
            pass
    return fallback


def _custom_palette(rgb):
    """Builds a rich 3-stop gradient and ambient edge glow from any user-chosen RGB color."""
    r, g, b = rgb
    # Brighter shifted start, exact user color in center, deeper hue-shifted end
    c_start = (min(255, int(r * 0.75 + 75)), min(255, int(g * 0.85 + 65)), min(255, int(b * 0.90 + 50)))
    c_end = (min(255, int(r * 0.60 + b * 0.35)), min(255, int(g * 0.55 + r * 0.25)), min(255, int(b * 0.65 + g * 0.30)))
    top_bg = (max(4, r // 10), max(4, g // 10), max(6, b // 10))
    bot_bg = (max(4, c_end[0] // 10), max(4, c_end[1] // 10), max(6, c_end[2] // 10))
    return ([c_start, (r, g, b), c_end], (r, g, b), top_bg, bot_bg)


CLOCK_THEMES = {
    "aurora": ([(0, 245, 212), (0, 187, 249), (168, 85, 247)], (0, 229, 255), (8, 18, 28), (18, 10, 30)),
    "sunset": ([(255, 195, 65), (255, 56, 128), (147, 72, 255)], (255, 150, 80), (28, 12, 20), (16, 10, 30)),
    "ocean": ([(94, 248, 212), (0, 212, 255), (82, 121, 255)], (0, 229, 255), (8, 20, 30), (10, 14, 30)),
    "cyber": ([(0, 245, 255), (59, 130, 246), (244, 63, 180)], (0, 245, 255), (8, 18, 30), (26, 8, 24)),
    "fire": ([(255, 75, 60), (255, 155, 40), (255, 225, 95)], (255, 155, 40), (28, 10, 8), (24, 16, 6)),
}


def _time_palette(hour, theme="auto", custom_color="#00e5ff"):
    """Returns (digit_stops, accent_rgb, top_bg, bot_bg) for the selected theme or time of day."""
    t = str(theme or "auto").lower()
    if t == "custom":
        return _custom_palette(_hex_to_rgb(custom_color))
    if t in CLOCK_THEMES:
        return CLOCK_THEMES[t]
    if 5 <= hour < 11:
        return ([(255, 224, 102), (255, 132, 84), (247, 56, 138)], (255, 209, 102), (28, 12, 16), (12, 14, 28))
    if 11 <= hour < 17:
        return CLOCK_THEMES["ocean"]
    if 17 <= hour < 22:
        return CLOCK_THEMES["sunset"]
    return CLOCK_THEMES["aurora"]


def idle_scene(unread=0, weather_data=None, now_dt=None, options=None):
    """Modern Gradient Digital Clock with Date, Ambient Edge Glow & Weather."""
    opts = options or {}
    now = now_dt or datetime.datetime.now()
    time_str = now.strftime("%H:%M")
    dow = GERMAN_DAYS[now.weekday()]
    date_str = now.strftime("%d.%m.")

    digit_stops, accent_rgb, top_bg, bot_bg = _time_palette(
        now.hour,
        theme=opts.get("clock_theme", "auto"),
        custom_color=opts.get("clock_color", CYAN),
    )
    mid_col = _gradient_sample(digit_stops, 0.5)

    # Build static base canvas once (background glow + header + divider + weather)
    base = Image.new("RGB", (32, 32), "black")
    draw_b = ImageDraw.Draw(base)

    # 1. Subtle atmospheric top & bottom ambient glow (keeps center pure black for max contrast)
    for y in range(6):
        fade = (6 - y) / 6.0 * 0.85
        c_row = (int(top_bg[0] * fade), int(top_bg[1] * fade), int(top_bg[2] * fade))
        draw_b.line((0, y, 31, y), fill=c_row)
    for y in range(25, 32):
        fade = (y - 24) / 7.0 * 0.85
        c_row = (int(bot_bg[0] * fade), int(bot_bg[1] * fade), int(bot_bg[2] * fade))
        draw_b.line((0, y, 31, y), fill=c_row)

    # 2. Top header: Day-of-week (accent) + Date (crisp ice-white)
    w_dow = pixel_font.measure_text(dow, font_type="mini")
    w_date = pixel_font.measure_text(date_str, font_type="mini")
    gap_top = 3
    tx = max(1, (32 - (w_dow + gap_top + w_date)) // 2)
    pixel_font.draw_text(base, (tx, 1), dow, fill=accent_rgb, font_type="mini")
    pixel_font.draw_text(base, (tx + w_dow + gap_top, 1), date_str, fill="#dce6f5", font_type="mini")
    if unread:
        draw_b.point((30, 1), fill=BLURPLE)
        draw_b.point((31, 1), fill=BLURPLE)

    # 3. Sleek gradient hairline dividers at y=7 and y=22
    for gx in range(2, 30):
        edge_fade = 1.0 - abs(gx - 15.5) / 14.5
        edge_fade = max(0.08, edge_fade * 0.55)
        gc = _gradient_sample(digit_stops, (gx - 2) / 27.0)
        line_c = (int(gc[0] * edge_fade), int(gc[1] * edge_fade), int(gc[2] * edge_fade))
        base.putpixel((gx, 7), line_c)
        base.putpixel((gx, 22), line_c)

    # 4. Large 5x7 Digital Clock (HH MM) rendered via mask with smooth 2D color gradient
    w_clock = pixel_font.measure_text(time_str, font_type="clock")
    cx = (32 - w_clock) // 2
    cy = 11
    mask = Image.new("L", (32, 32), 0)
    pixel_font.draw_text(mask, (cx, cy), time_str.replace(":", " "), fill=255, font_type="clock")
    for py in range(cy, cy + 7):
        v_t = (py - cy) / 6.0  # Vertical brightness/saturation curve (brighter top -> richer bottom)
        for px in range(32):
            if mask.getpixel((px, py)) > 128:
                h_t = max(0.0, min(1.0, (px - cx) / max(1, w_clock - 1)))
                gc = _gradient_sample(digit_stops, h_t)
                # Subtle top highlight for 3D crispness
                lit = _lerp_color((255, 255, 255), gc, 0.45 + 0.55 * v_t)
                base.putpixel((px, py), lit)

    # 5. Bottom Weather Bar (y=24..30)
    if weather_data and "temp" in weather_data:
        temp = weather_data["temp"]
        w_icon = weather_data.get("icon", "cloud")
        temp_str = f"{temp}°C"
        w_temp = pixel_font.measure_text(temp_str, font_type="mini")
        icon_w = 5
        gap_w = 3
        start_x = max(1, (32 - (icon_w + gap_w + w_temp)) // 2)
        _draw_mini_weather(base, w_icon, ox=start_x, oy=25)
        temp_col = "#64d2ff" if temp <= 4 else ("#ff9f43" if temp >= 22 else "#eef4ff")
        pixel_font.draw_text(base, (start_x + icon_w + gap_w, 25), temp_str, fill=temp_col, font_type="mini")
    else:
        for gx in range(8, 24):
            gc = _gradient_sample(digit_stops, (gx - 8) / 15.0)
            base.putpixel((gx, 27), (gc[0] // 3, gc[1] // 3, gc[2] // 3))

    # Measure colon x-position from "HH" width
    hh_w = pixel_font.measure_text(time_str[:2], font_type="clock")
    colon_x = cx + hh_w + 1

    # 10-frame smooth sinusoidal colon breath (only 2px changes -> ~1 KB total GIF!)
    frames, durations = [], []
    for k in range(10):
        t = 0.5 + 0.5 * math.sin(2.0 * math.pi * k / 10.0)
        eased = t * t * (3.0 - 2.0 * t)
        c_col = _lerp_color((mid_col[0] // 7, mid_col[1] // 7, mid_col[2] // 7), _lerp_color((255, 255, 255), mid_col, 0.5), eased)
        frame = base.copy()
        frame.putpixel((colon_x, cy + 1), c_col)
        frame.putpixel((colon_x, cy + 4), c_col)
        frames.append(frame)
        durations.append(90)

    return _encode(frames, durations)


FLIP_DIGITS = {
    "0": [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "1": ["..#..", ".##..", "..#..", "..#..", "..#..", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."],
    "2": ["#####", "....#", "....#", "....#", "....#", "#####", "#....", "#....", "#....", "#....", "#####"],
    "3": ["#####", "....#", "....#", "....#", "....#", "#####", "....#", "....#", "....#", "....#", "#####"],
    "4": ["#...#", "#...#", "#...#", "#...#", "#...#", "#####", "....#", "....#", "....#", "....#", "....#"],
    "5": ["#####", "#....", "#....", "#....", "#....", "#####", "....#", "....#", "....#", "....#", "#####"],
    "6": ["#####", "#....", "#....", "#....", "#....", "#####", "#...#", "#...#", "#...#", "#...#", "#####"],
    "7": ["#####", "....#", "....#", "....#", "....#", "...#.", "..#..", "..#..", ".#...", ".#...", ".#..."],
    "8": ["#####", "#...#", "#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#", "#...#", "#####"],
    "9": ["#####", "#...#", "#...#", "#...#", "#...#", "#####", "....#", "....#", "....#", "....#", "#####"],
}


def _draw_flip_digit(draw, ox, oy, char):
    glyph = FLIP_DIGITS.get(char, FLIP_DIGITS["0"])
    for gy, row in enumerate(glyph):
        y = oy + gy
        if gy < 5:
            c = WHITE
        elif gy == 5:
            c = "#9aa6bc"  # Subtle split-seam shading across middle bar
        else:
            c = "#dbe3f0"
        for gx, ch in enumerate(row):
            if ch == "#":
                draw.point((ox + gx, y), fill=c)


def _draw_split_card(draw, x0, y0, x1, y1, split_y):
    """Draws a 3D two-tone split-flap card with rounded corners, split seam, and metallic hinges."""
    # Top flap (lit from above)
    draw.rectangle((x0, y0 + 1, x1, split_y - 1), fill="#1d2230")
    draw.line((x0 + 1, y0, x1 - 1, y0), fill="#282f42")
    # Bottom flap (slightly darker for 3D depth)
    draw.rectangle((x0, split_y + 1, x1, y1 - 1), fill="#131722")
    draw.line((x0 + 1, y1, x1 - 1, y1), fill="#0c0f17")
    # Pitch-black split seam + metallic side hinges
    draw.line((x0 + 1, split_y, x1 - 1, split_y), fill="#06070a")
    draw.point((x0, split_y), fill="#7b879e")
    draw.point((x1, split_y), fill="#7b879e")


def flip_clock_scene(unread=0, weather_data=None, now_dt=None, options=None):
    """3D Split-Flap Flip Clock:
    Two-tone shaded flap cards, metallic hinges, split seam, colored day/date header,
    smoothly pulsing colon, and colored mini weather icon + temperature.
    """
    opts = options or {}
    style = opts.get("flip_style", "horizontal")
    clock_color = opts.get("clock_color", CYAN)
    # Use vibrant cyan accent if user's clock_color is pure white so accents pop
    accent = CYAN if str(clock_color).lower() in ("#ffffff", "white") else clock_color

    now = now_dt or datetime.datetime.now()
    hour_str = now.strftime("%H")
    min_str = now.strftime("%M")
    dow = GERMAN_DAYS[now.weekday()]
    date_str = now.strftime("%d.%m")

    # 4-frame smooth colon pulse (bright -> soft -> dim -> soft)
    colon_shades = [accent, "#1d5c6e", "#10141e", "#1d5c6e"] if accent == CYAN else [accent, "#444b5e", "#10141e", "#444b5e"]
    frames, durations = [], [600, 350, 600, 350]

    for c_col in colon_shades:
        img = Image.new("RGB", (32, 32), "black")
        draw = ImageDraw.Draw(img)

        if style == "vertical":
            # Vertical Flip Clock (Stacked 3D cards)
            _draw_split_card(draw, 3, 2, 28, 14, 8)
            pixel_font.draw_text(img, (9, 4), hour_str[0], fill=WHITE, font_type="clock")
            pixel_font.draw_text(img, (17, 4), hour_str[1], fill=WHITE, font_type="clock")

            _draw_split_card(draw, 3, 17, 28, 29, 23)
            pixel_font.draw_text(img, (9, 19), min_str[0], fill=WHITE, font_type="clock")
            pixel_font.draw_text(img, (17, 19), min_str[1], fill=WHITE, font_type="clock")

            draw.point((15, 15), fill=c_col)
            draw.point((16, 15), fill=c_col)

        else:
            # Horizontal 3D Split-Flap Clock
            # 1. Top header: Accent Day-of-Week + Crisp Silver Date
            w_dow = pixel_font.measure_text(dow, font_type="mini")
            w_date = pixel_font.measure_text(date_str, font_type="mini")
            gap_top = 3
            total_top_w = w_dow + gap_top + w_date
            tx = max(1, (32 - total_top_w) // 2)
            pixel_font.draw_text(img, (tx, 1), dow, fill=accent, font_type="mini")
            pixel_font.draw_text(img, (tx + w_dow + gap_top, 1), date_str, fill="#9aa8bf", font_type="mini")
            if unread:
                draw.point((30, 1), fill=BLURPLE)
                draw.point((31, 1), fill=BLURPLE)

            # 2. Split-Flap Cards (Hours left, Minutes right)
            _draw_split_card(draw, 1, 8, 14, 22, 15)
            _draw_split_card(draw, 17, 8, 30, 22, 15)

            # 3. Bold 5x11 Numerals
            _draw_flip_digit(draw, 2, 10, hour_str[0])
            _draw_flip_digit(draw, 8, 10, hour_str[1])
            _draw_flip_digit(draw, 18, 10, min_str[0])
            _draw_flip_digit(draw, 24, 10, min_str[1])

            # 4. Center pulsing colon (2x2 dots)
            draw.rectangle((15, 12, 16, 13), fill=c_col)
            draw.rectangle((15, 17, 16, 18), fill=c_col)

            # 5. Bottom bar: Colored Mini Weather Icon + Temperature
            if weather_data and "temp" in weather_data:
                temp = weather_data["temp"]
                w_icon = weather_data.get("icon", "cloud")
                temp_str = f"{temp}°"
                w_temp = pixel_font.measure_text(temp_str, font_type="mini")
                icon_w = 5
                gap_w = 3
                start_x = max(1, (32 - (icon_w + gap_w + w_temp)) // 2)
                _draw_mini_weather(img, w_icon, ox=start_x, oy=25)
                temp_col = "#64d2ff" if temp <= 4 else ("#ffb300" if temp >= 22 else "#d0dae8")
                pixel_font.draw_text(img, (start_x + icon_w + gap_w, 25), temp_str, fill=temp_col, font_type="mini")
            else:
                draw.line((13, 27, 18, 27), fill="#1b202c")
                draw.point((15, 27), fill=c_col)
                draw.point((16, 27), fill=c_col)

        frames.append(img)

    return _encode(frames, durations)


def weather_scene(weather_data, options=None):
    """Full 32x32 retro weather scene: animated icon, bold temp, and marquee details."""
    opts = options or {}
    city = weather_data.get("city", "Wetter")
    temp = weather_data.get("temp", 0)
    icon_type = weather_data.get("icon", "cloud")
    condition = weather_data.get("condition", "")
    t_max = weather_data.get("temp_max")
    t_min = weather_data.get("temp_min")

    temp_str = f"{temp}°C"
    temp_color = WHITE

    # Marquee text: City · Condition · Max / Min
    parts = [(city, WHITE)]
    if condition:
        parts.extend([("  ·  ", WHITE), (condition, WHITE)])
    if t_max is not None and t_min is not None:
        parts.extend([("  ·  ", WHITE), (f"Max {t_max}° Min {t_min}°", WHITE)])

    text = Marquee(parts, box=32)
    step_px = 2 if text.cycle else 1
    steps = max(1, (text.cycle + step_px - 1) // step_px) if text.cycle else 8

    frames, durations = [], []
    for f_idx in range(steps):
        image = Image.new("RGB", (32, 32), "black")
        draw = ImageDraw.Draw(image)

        # 1. Animated weather icon at (9, 0)
        _draw_weather_icon(image, icon_type, frame_idx=f_idx, offset=(9, 0))

        # 2. Big Temperature in FONT_CLOCK (rows 14..20)
        w_temp = pixel_font.measure_text(temp_str, font_type="clock")
        cx = max(1, (32 - w_temp) // 2)
        pixel_font.draw_text(image, (cx, 14), temp_str, fill=temp_color, font_type="clock")

        # 3. Subtle divider line at row 22
        draw.line((2, 22, 29, 22), fill="#262a33")
        draw.point((15, 22), fill=WHITE)
        draw.point((16, 22), fill=WHITE)

        # 4. Scrolling details text at rows 23..31 (2px/step for compact BLE payload)
        text.paste(image, 0, 23, (f_idx * step_px) if text.cycle else 0)

        frames.append(image)
        durations.append((HOLD_MS + 160) if (f_idx == 0 and text.cycle) else 160)

    return _encode(frames, durations), sum(durations) / 1000


def timer_scene(remaining_sec, total_sec, label="FOKUS", finished=False):
    """32x32 Pomodoro / Focus Timer with gradient perimeter progress ring."""
    if finished:
        frames, durations = [], [350, 350]
        for bright in (True, False):
            img = Image.new("RGB", (32, 32), "black")
            draw = ImageDraw.Draw(img)
            col = "#1ed760" if bright else "#ffb300"
            draw.rectangle((0, 0, 31, 31), outline=col)
            draw.rectangle((1, 1, 30, 30), outline="#0f3d20" if bright else "#443000")
            w_lbl = pixel_font.measure_text(label, font_type="mini")
            pixel_font.draw_text(img, ((32 - w_lbl) // 2, 6), label, fill="#9aa8bf", font_type="mini")
            w_done = pixel_font.measure_text("DONE!", font_type="clock")
            pixel_font.draw_text(img, ((32 - w_done) // 2, 14), "DONE!", fill=col, font_type="clock")
            frames.append(img)
        return _encode(frames, durations)

    pct = max(0.0, min(1.0, remaining_sec / max(1.0, total_sec)))
    # Perimeter path (clockwise starting at top-center x=16, y=0)
    ring = (
        [(x, 0) for x in range(16, 32)]
        + [(31, y) for y in range(1, 32)]
        + [(x, 31) for x in range(30, -1, -1)]
        + [(0, y) for y in range(30, -1, -1)]
        + [(x, 0) for x in range(1, 16)]
    )
    lit_count = max(1, int(round(pct * len(ring))))
    stops = [(0, 245, 212), (0, 187, 249), (168, 85, 247)] if pct > 0.25 else [(255, 179, 0), (255, 77, 109), (255, 46, 126)]

    if remaining_sec > 60:
        mins = int(math.ceil(remaining_sec / 60.0))
        time_txt = f"{mins}M"
    else:
        secs = max(1, int(math.ceil(remaining_sec)))
        time_txt = f"0:{secs:02d}"

    base = Image.new("RGB", (32, 32), "black")
    for idx, (rx, ry) in enumerate(ring):
        if idx < lit_count:
            col = _gradient_sample(stops, idx / max(1, len(ring) - 1))
        else:
            col = (18, 22, 30)
        base.putpixel((rx, ry), col)

    w_lbl = pixel_font.measure_text(label, font_type="mini")
    pixel_font.draw_text(base, ((32 - w_lbl) // 2, 5), label, fill="#8e9db5", font_type="mini")

    w_t = pixel_font.measure_text(time_txt, font_type="clock")
    pixel_font.draw_text(base, ((32 - w_t) // 2, 13), time_txt, fill=WHITE, font_type="clock")

    # Subtle pulsing center dot below time
    frames, durations = [], [700, 700]
    mid = _gradient_sample(stops, 0.5)
    for lit in (True, False):
        f = base.copy()
        dot_c = mid if lit else (mid[0] // 5, mid[1] // 5, mid[2] // 5)
        f.putpixel((15, 24), dot_c)
        f.putpixel((16, 24), dot_c)
        frames.append(f)
    return _encode(frames, durations)


def twitch_live_scene(streamer, game="LIVE"):
    """Twitch purple header with pulsing red LIVE dot + streamer & game marquee."""
    parts = [(streamer.upper(), WHITE)]
    if game and game.lower() != "live":
        parts.extend([("  ·  ", "#a970ff"), (game, "#e9d8fd")])
    text = Marquee(parts, box=32, font_type="mini")
    step_px = 2 if text.cycle else 1
    steps = max(4, (text.cycle + step_px - 1) // step_px) if text.cycle else 4

    frames, durations = [], []
    for i in range(steps):
        img = Image.new("RGB", (32, 32), "black")
        draw = ImageDraw.Draw(img)
        # Twitch purple header bar
        draw.rectangle((0, 0, 31, 10), fill="#9146ff")
        dot_col = "#ff2e4c" if (i % 2 == 0) else "#7a1426"
        draw.rectangle((3, 3, 6, 6), fill=dot_col)
        pixel_font.draw_text(img, (9, 3), "LIVE", fill=WHITE, font_type="mini")

        text.paste(img, 0, 16, (i * step_px) if text.cycle else 0)
        frames.append(img)
        durations.append((HOLD_MS + 160) if (i == 0 and text.cycle) else 220)
    return _encode(frames, durations)


def game_scene(game_name, accent="#00e5ff", elapsed_min=0, cpu_percent=0):
    """Auto-Game-Detection HUD: pixel controller icon, game title, session time & CPU bar."""
    accent_rgb = _hex_to_rgb(accent)
    gamepad = [
        "..XXX.XXX..",
        ".XXXXXXXXX.",
        "XX.XXXXX.XX",
        "X.X.XXX.X.X",
        "XX.XXXXX.XX",
        ".XXX...XXX.",
    ]
    base = Image.new("RGB", (32, 32), "black")
    draw = ImageDraw.Draw(base)
    # Subtle top glow
    draw.line((0, 0, 31, 0), fill=(accent_rgb[0] // 4, accent_rgb[1] // 4, accent_rgb[2] // 4))
    for gy, row in enumerate(gamepad):
        for gx, ch in enumerate(row):
            if ch == "X":
                base.putpixel((2 + gx, 3 + gy), accent_rgb)

    time_lbl = f"{elapsed_min}M" if elapsed_min > 0 else "PLAY"
    w_tl = pixel_font.measure_text(time_lbl, font_type="mini")
    pixel_font.draw_text(base, (30 - w_tl, 4), time_lbl, fill="#9aa8bf", font_type="mini")

    # Game title
    w_g = pixel_font.measure_text(game_name, font_type="mini")
    if w_g <= 30:
        pixel_font.draw_text(base, ((32 - w_g) // 2, 14), game_name, fill=WHITE, font_type="mini")
    else:
        pixel_font.draw_text(base, (1, 14), game_name[:7], fill=WHITE, font_type="mini")

    # Bottom CPU bar
    draw.rectangle((2, 26, 29, 28), fill="#141822")
    fill_w = max(1, min(28, int(round((cpu_percent / 100.0) * 28))))
    draw.rectangle((2, 26, 1 + fill_w, 28), fill=accent_rgb)

    # Subtle pulsing active pixel
    frames, durations = [], [800, 800]
    for lit in (True, False):
        f = base.copy()
        f.putpixel((15, 22), accent_rgb if lit else (accent_rgb[0] // 5, accent_rgb[1] // 5, accent_rgb[2] // 5))
        f.putpixel((16, 22), accent_rgb if lit else (accent_rgb[0] // 5, accent_rgb[1] // 5, accent_rgb[2] // 5))
        frames.append(f)
    return _encode(frames, durations)


WOW_CLASS_COLORS = {
    "WARRIOR": "#c69b6d",
    "MAGE": "#3fc7eb",
    "ROGUE": "#fff468",
    "PRIEST": "#ffffff",
    "WARLOCK": "#8788ee",
    "PALADIN": "#f48cba",
    "DRUID": "#ff7c0a",
    "HUNTER": "#aad372",
    "SHAMAN": "#0070dd",
    "DEATHKNIGHT": "#c41e3a",
    "MONK": "#00ff98",
    "DEMONHUNTER": "#a330c9",
    "EVOKER": "#33937f",
}


def wow_scene(stats):
    """World of Warcraft Character Stats HUD in official Blizzard class colors."""
    name = str(stats.get("name", "Hero"))
    cls_key = str(stats.get("class", "WARRIOR")).upper()
    cls_hex = WOW_CLASS_COLORS.get(cls_key, "#00e5ff")
    cls_rgb = _hex_to_rgb(cls_hex)
    level = int(stats.get("level", 80))
    ilvl = int(stats.get("ilvl", 0))
    crit = stats.get("crit", 0)
    haste = stats.get("haste", 0)
    mastery = stats.get("mastery", 0)
    vers = stats.get("vers", 0)
    gold = int(stats.get("gold", 0))
    zone = str(stats.get("zone", ""))

    # Build stats marquee
    parts = [
        (f"CRIT {crit}%", "#ff6b6b"),
        (" · ", "#64748b"),
        (f"HASTE {haste}%", CYAN),
        (" · ", "#64748b"),
        (f"MAST {mastery}%", "#c084fc"),
    ]
    if vers:
        parts.extend([(" · ", "#64748b"), (f"VERS {vers}%", GREEN)])
    if gold:
        g_str = f"{gold // 1000}K G" if gold >= 10000 else f"{gold}G"
        parts.extend([(" · ", "#64748b"), (g_str, "#ffd166")])
    if zone:
        parts.extend([(" · ", "#64748b"), (zone, "#cbd5e1")])

    text = Marquee(parts, box=32, font_type="mini")
    step_px = 2 if text.cycle else 1
    steps = max(1, (text.cycle + step_px - 1) // step_px) if text.cycle else 1

    # Pixel sword (7x7)
    sword = [
        ".....XX",
        "....XXX",
        "...XXX.",
        ".X.XX..",
        "..XX...",
        ".X.X...",
        "X......",
    ]
    base = Image.new("RGB", (32, 32), "black")
    draw_b = ImageDraw.Draw(base)
    draw_b.rectangle((0, 0, 31, 8), fill=(cls_rgb[0] // 6, cls_rgb[1] // 6, cls_rgb[2] // 6))
    for sy, row in enumerate(sword):
        for sx, ch in enumerate(row):
            if ch == "X":
                base.putpixel((1 + sx, 1 + sy), cls_rgb)

    top_lbl = f"IL{ilvl}" if ilvl > 0 else f"LV{level}"
    w_tl = pixel_font.measure_text(top_lbl, font_type="mini")
    pixel_font.draw_text(base, (31 - w_tl, 2), top_lbl, fill="#ffd166" if ilvl > 0 else WHITE, font_type="mini")

    # Character name in class color
    w_name = pixel_font.measure_text(name, font_type="mini")
    nx = max(1, (32 - w_name) // 2)
    pixel_font.draw_text(base, (nx, 12), name[:8] if w_name > 30 else name, fill=cls_hex, font_type="mini")

    draw_b.line((2, 20, 29, 20), fill=(cls_rgb[0] // 3, cls_rgb[1] // 3, cls_rgb[2] // 3))

    frames, durations = [], []
    for s_idx in range(steps):
        img = base.copy()
        text.paste(img, 0, 23, (s_idx * step_px) if text.cycle else 0)
        frames.append(img)
        durations.append((HOLD_MS + 180) if (s_idx == 0 and text.cycle) else 220)

    return _encode(frames, durations)


def first_frames(gif, count=4):
    """Decode a few frames (for previews/tests)."""
    with Image.open(io.BytesIO(gif)) as image:
        out = []
        for i in range(min(count, image.n_frames)):
            image.seek(i * max(1, image.n_frames // count))
            out.append(image.convert("RGB"))
        return out, image.n_frames
