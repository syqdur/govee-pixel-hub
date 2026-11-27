"""Bluetooth BLE transport driver for the Govee H6630."""
import asyncio
import io
from pathlib import Path
import time
from typing import Any, Dict, Optional

from PIL import Image

from pixel_ble import BlePixelClient
from pixel_frame import gif_frame


class BleDriver:
    """Manages the BLE connection and uploads scenes as looping GIFs to the H6630."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.client = BlePixelClient()
        self.last_upload_time: float = 0.0
        self.last_transfer_duration: float = 0.0
        self.last_bytes: int = 0
        self.total_uploads: int = 0
        self.last_error: Optional[str] = None
        self.is_connected: bool = False
        self.last_gif: Optional[bytes] = None
        self.last_png: Optional[bytes] = None

    async def upload(self, gif_bytes: bytes, label: str = "scene") -> Dict[str, Any]:
        """Uploads a GIF payload to the H6630."""
        self.last_gif = gif_bytes
        (self.output_dir / "live-scene.gif").write_bytes(gif_bytes)

        # Extract and save first frame as PNG for previews
        try:
            with Image.open(io.BytesIO(gif_bytes)) as img:
                img.seek(0)
                png_buf = io.BytesIO()
                img.convert("RGB").save(png_buf, format="PNG")
                self.last_png = png_buf.getvalue()
                (self.output_dir / "live-frame.png").write_bytes(self.last_png)
        except Exception:
            pass

        self.client.activated = False  # Ensure 33 05 activation on device
        try:
            result = await self.client.send_payload(gif_frame(gif_bytes))
            self.last_upload_time = time.time()
            self.last_transfer_duration = result.get("seconds", 0.0)
            self.last_bytes = len(gif_bytes)
            self.total_uploads += 1
            self.last_error = None
            print(f"BLE Upload [{label}]: {len(gif_bytes)} bytes in {self.last_transfer_duration}s", flush=True)
            return result
        except Exception as err:
            self.last_error = f"{type(err).__name__}: {err}"
            print(f"BLE Upload error: {self.last_error}", flush=True)
            try:
                await self.client.close()
            except Exception:
                pass
            self.client = BlePixelClient()
            raise

    async def turn_off(self) -> None:
        """Sends command to turn off H6630 display."""
        try:
            await self.client.turn_off()
        except Exception as err:
            print(f"Error turning off BLE device: {err}", flush=True)

    async def turn_on(self) -> None:
        """Sends command to turn on H6630 display."""
        try:
            await self.client.turn_on()
        except Exception as err:
            print(f"Error turning on BLE device: {err}", flush=True)

    async def close(self) -> None:
        await self.client.close()
        self.is_connected = False

    def get_status(self) -> Dict[str, Any]:
        return {
            "connected": self.is_connected,
            "last_upload_time": self.last_upload_time,
            "last_duration_seconds": self.last_transfer_duration,
            "last_bytes": self.last_bytes,
            "total_uploads": self.total_uploads,
            "last_error": self.last_error,
        }
