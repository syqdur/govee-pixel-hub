"""Windows System Tray icon for quick Govee Pixel Hub control."""
import asyncio
import threading
import webbrowser
from typing import Optional

from PIL import Image, ImageDraw


def _build_tray_image() -> Image.Image:
    """Draws a crisp 64x64 glowing cyan/purple pixel icon for the Windows System Tray."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((2, 2, 61, 61), 14, fill=(18, 22, 34, 255), outline=(0, 229, 255, 255), width=4)
    # Stylized pixel "G" in the center
    cyan = (0, 229, 255, 255)
    purple = (168, 85, 247, 255)
    draw.rectangle((18, 16, 46, 23), fill=cyan)
    draw.rectangle((18, 16, 25, 48), fill=cyan)
    draw.rectangle((18, 41, 46, 48), fill=purple)
    draw.rectangle((39, 30, 46, 48), fill=purple)
    draw.rectangle((31, 30, 46, 36), fill=purple)
    return img


class HubTrayIcon:
    """Manages the Windows System Tray icon in a background thread."""

    def __init__(self, hub, loop: asyncio.AbstractEventLoop):
        self.hub = hub
        self.loop = loop
        self.icon = None
        self.thread: Optional[threading.Thread] = None

    def start(self) -> None:
        try:
            import pystray
        except ImportError:
            return

        port = int(self.hub.config.get("web_port", 5000))
        url = f"http://127.0.0.1:{port}/"

        def open_dashboard(icon=None, item=None):
            webbrowser.open(url)

        def start_focus(icon=None, item=None):
            self.hub.timer.start_timer(25, "FOKUS")

        def stop_focus(icon=None, item=None):
            self.hub.timer.stop_timer()

        def show_clock(icon=None, item=None):
            self.hub.priority_manager.force_display("clock", 30.0)

        def display_on(icon=None, item=None):
            asyncio.run_coroutine_threadsafe(self.hub.ble_driver.turn_on(), self.loop)

        def display_off(icon=None, item=None):
            asyncio.run_coroutine_threadsafe(self.hub.ble_driver.turn_off(), self.loop)

        def quit_hub(icon=None, item=None):
            try:
                fut = asyncio.run_coroutine_threadsafe(self.hub.stop_and_turn_off(), self.loop)
                fut.result(timeout=4.0)
            except Exception:
                self.hub.running = False
            self.stop()

        menu = pystray.Menu(
            pystray.MenuItem("Web-Dashboard öffnen", open_dashboard, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("25m Fokus-Timer", start_focus),
            pystray.MenuItem("Timer stoppen", stop_focus),
            pystray.MenuItem("Uhr anzeigen", show_clock),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Display An", display_on),
            pystray.MenuItem("Display Aus", display_off),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Hub beenden", quit_hub),
        )

        self.icon = pystray.Icon("GoveePixelHub", _build_tray_image(), "Govee H6630 Pixel Hub", menu)
        try:
            self.icon.run_detached()
        except Exception:
            self.thread = threading.Thread(target=self.icon.run, daemon=True)
            self.thread.start()

    def stop(self) -> None:
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass
            self.icon = None
