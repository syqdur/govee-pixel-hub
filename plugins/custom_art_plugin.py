"""Custom 32x32 Pixel Art & Image/GIF Upload plugin."""
import hashlib
import io
import time
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageOps
from core.plugin_base import PluginBase
import scenes


class CustomArtPlugin(PluginBase):
    name = "custom_art"
    display_name = "Pixel-Art Studio"
    priority = 65
    enabled = True

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.gif_bytes: Optional[bytes] = None
        self.art_hash: Optional[str] = None
        self.expires_at: float = 0.0  # 0 = pinned until cleared

    def set_pixels(self, pixels: List[str], duration: float = 0.0) -> bool:
        """Accepts 1024 hex color strings (32x32) from the Web Pixel Studio."""
        if not pixels or len(pixels) != 1024:
            return False
        img = Image.new("RGB", (32, 32), "black")
        for idx, hex_col in enumerate(pixels):
            s = str(hex_col or "#000000").strip().lstrip("#")
            if len(s) == 6:
                try:
                    rgb = (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
                    img.putpixel((idx % 32, idx // 32), rgb)
                except ValueError:
                    pass
        self.gif_bytes = scenes._encode([img], [1000])
        self.art_hash = hashlib.md5(self.gif_bytes).hexdigest()[:8]
        self.expires_at = (time.monotonic() + duration) if duration > 0 else 0.0
        return True

    def set_image_bytes(self, raw_bytes: bytes, duration: float = 0.0) -> bool:
        """Accepts uploaded PNG/JPG/GIF bytes and converts to 32x32 H6630 GIF."""
        if not raw_bytes:
            return False
        try:
            with Image.open(io.BytesIO(raw_bytes)) as orig:
                n_frames = getattr(orig, "n_frames", 1)
                frames, durations = [], []
                step = max(1, n_frames // 24) if n_frames > 24 else 1
                for i in range(0, n_frames, step):
                    orig.seek(i)
                    frame = ImageOps.fit(orig.convert("RGB"), (32, 32), method=Image.Resampling.LANCZOS)
                    frames.append(frame)
                    dur = max(60, int(orig.info.get("duration", 120) * step))
                    durations.append(dur)
                if not frames:
                    return False
                self.gif_bytes = scenes._encode(frames, durations)
                self.art_hash = hashlib.md5(self.gif_bytes).hexdigest()[:8]
                self.expires_at = (time.monotonic() + duration) if duration > 0 else 0.0
                return True
        except Exception:
            return False

    def clear(self) -> None:
        self.gif_bytes = None
        self.art_hash = None
        self.expires_at = 0.0

    def should_display(self) -> bool:
        if not self.enabled or not self.gif_bytes:
            return False
        if self.expires_at > 0 and time.monotonic() >= self.expires_at:
            self.clear()
            return False
        return True

    def get_state_key(self) -> Any:
        if not self.should_display():
            return None
        return (self.name, self.art_hash)

    def render(self) -> Tuple[bytes, float]:
        if not self.gif_bytes:
            return b"", 0.0
        return self.gif_bytes, 10.0

    def get_status_info(self) -> Dict[str, Any]:
        info = super().get_status_info()
        info.update({
            "active_art": self.should_display(),
            "art_hash": self.art_hash,
            "pinned": self.expires_at == 0.0 and self.should_display(),
        })
        return info
