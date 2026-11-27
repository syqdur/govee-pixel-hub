"""Govee Pixel Hub: Main orchestrator for H6630 plugins, BLE streaming, and Web UI."""
import argparse
import asyncio
import gc
import json
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional

from core.ble_driver import BleDriver
from core.lan_control import DEFAULT_LAN_IP, is_night_time, set_lan_brightness
from core.priority_manager import PriorityManager
from core.tray_icon import HubTrayIcon
from core.web_server import PixelWebServer
from plugins.clock_plugin import ClockPlugin
from plugins.custom_art_plugin import CustomArtPlugin
from plugins.discord_plugin import DiscordPlugin
from plugins.discord_voice_plugin import DiscordVoicePlugin
from plugins.game_plugin import GamePlugin
from plugins.hardware_plugin import HardwarePlugin
from plugins.spotify_plugin import SpotifyPlugin
from plugins.timer_plugin import TimerPlugin
from plugins.twitch_plugin import TwitchPlugin
from plugins.weather_plugin import WeatherPlugin
from plugins.wow_plugin import WoWPlugin

ROOT = Path(__file__).parent
OUTPUT = ROOT / "spotify-output"
CONFIG_FILE = ROOT / "display_hub.json"
PID_FILE = OUTPUT / "worker.json"
LOG_FILE = OUTPUT / "worker.log"


class _TeeLogger:
    def __init__(self, target, filename):
        self.terminal = target
        self.filename = filename
        self._f = None

    def _get_f(self):
        if self._f is None:
            try:
                OUTPUT.mkdir(exist_ok=True)
                self._f = open(self.filename, "a", encoding="utf-8", buffering=1)
            except Exception:
                pass
        return self._f

    def write(self, message):
        if self.terminal:
            try:
                self.terminal.write(message)
                self.terminal.flush()
            except Exception:
                pass
        f = self._get_f()
        if f:
            try:
                f.write(message)
                f.flush()
            except Exception:
                pass

    def flush(self):
        if self.terminal:
            try:
                self.terminal.flush()
            except Exception:
                pass
        f = self._get_f()
        if f:
            try:
                f.flush()
            except Exception:
                pass


def setup_logging():
    OUTPUT.mkdir(exist_ok=True)
    sys.stdout = _TeeLogger(sys.stdout, LOG_FILE)
    sys.stderr = _TeeLogger(sys.stderr, LOG_FILE)


def acquire_single_instance_lock():
    """Returns mutex handle if this is the ONLY running hub instance, else None."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        mutex_name = "Local\\GoveePixelHub_SingleInstance"
        mutex = kernel32.CreateMutexW(None, False, mutex_name)
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            return None
        return mutex
    except Exception:
        return True


def trim_memory() -> None:
    """Forces garbage collection and releases cold memory pages back to Windows."""
    gc.collect()
    try:
        import ctypes
        pid = ctypes.windll.kernel32.GetCurrentProcessId()
        h = ctypes.windll.kernel32.OpenProcess(0x0100 | 0x0400, False, pid)
        if h:
            ctypes.windll.psapi.EmptyWorkingSet(h)
            ctypes.windll.kernel32.CloseHandle(h)
    except Exception:
        pass


DEFAULT_CONFIG = {
    "notify_apps": ["Discord"],
    "notify_min_seconds": 10,
    "show_message_text": True,
    "media_apps": ["spotify"],
    "idle_clock": True,
    "spotify_mini_clock": False,
    "eq_gradient": False,
    "clock_color": "#00e5ff",
    "carousel_seconds": 15,
    "hardware_enabled": True,
    "discord_voice_enabled": True,
    "voice_mode": "on_speaking",
    "voice_interrupts_music": False,
    "text_speed_ms": 220,
    "text_hold_ms": 0,
    "weather_enabled": True,
    "weather_carousel": False,
    "weather_city": "Berlin",
    "spotify_show_weather": True,
    "spotify_eq": False,
    "spotify_text_mode": "marquee",
    "spotify_ambient_breath": False,
    "progress_sync_seconds": 60,
    "clock_style": "digital",
    "clock_theme": "auto",
    "flip_style": "horizontal",
    "night_mode_enabled": False,
    "night_start": "23:00",
    "night_end": "07:00",
    "night_brightness": 20,
    "day_brightness": 100,
    "night_theme": "fire",
    "lan_ip": DEFAULT_LAN_IP,
    "discord_enabled": True,
    "twitch_enabled": True,
    "twitch_channels": [],
    "game_detection_enabled": True,
    "wow_enabled": True,
    "show_paused_spotify": False,
    "web_port": 5000,
}


class PixelHub:
    def __init__(self, config_path: Path = CONFIG_FILE):
        self.config_path = config_path
        self.config = self._load_config()
        self.ble_driver = BleDriver(OUTPUT)

        # Initialize plugins
        self.discord = DiscordPlugin(self.config)
        self.voice = DiscordVoicePlugin(self.config)
        self.twitch = TwitchPlugin(self.config)
        self.timer = TimerPlugin(self.config)
        self.custom_art = CustomArtPlugin(self.config)
        self.wow = WoWPlugin(self.config)
        self.game = GamePlugin(self.config)
        self.weather = WeatherPlugin(self.config)
        self.spotify = SpotifyPlugin(self.config, discord_plugin=self.discord, weather_plugin=self.weather)
        self.clock = ClockPlugin(self.config, discord_plugin=self.discord, weather_plugin=self.weather)
        self.hardware = HardwarePlugin(self.config)

        self.plugins = [self.discord, self.twitch, self.voice, self.timer, self.custom_art, self.spotify, self.wow, self.game, self.clock, self.weather, self.hardware]
        self.discord.enabled = bool(self.config.get("discord_enabled", True))
        self.twitch.enabled = bool(self.config.get("twitch_enabled", True))
        self.wow.enabled = bool(self.config.get("wow_enabled", True))
        self.game.enabled = bool(self.config.get("game_detection_enabled", True))
        self.voice.enabled = bool(self.config.get("discord_voice_enabled", False))
        self.hardware.enabled = bool(self.config.get("hardware_enabled", True))
        self.clock.enabled = bool(self.config.get("idle_clock", True))
        self.weather.enabled = bool(self.config.get("weather_enabled", True))

        self.priority_manager = PriorityManager(self.plugins, self.config)
        self.web_server = PixelWebServer(
            self, host="127.0.0.1", port=self.config.get("web_port", 5000)
        )

        self.shown_key = None
        self.running = False
        self._last_night_state: Optional[bool] = None
        self.tray_icon: Optional[HubTrayIcon] = None

    def _load_config(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            self.config_path.write_text(
                json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        try:
            return {**DEFAULT_CONFIG, **json.loads(self.config_path.read_text(encoding="utf-8"))}
        except Exception:
            return dict(DEFAULT_CONFIG)

    def save_config(self) -> None:
        self.config_path.write_text(
            json.dumps(self.config, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def update_config(self, updates: Dict[str, Any]) -> None:
        self.config.update(updates)
        self.save_config()
        self.shown_key = None
        self.priority_manager.config = self.config
        for p in self.plugins:
            p.config = self.config
        self.priority_manager.carousel_seconds = float(self.config.get("carousel_seconds", 15.0))
        if "hardware_enabled" in updates:
            self.hardware.enabled = bool(updates["hardware_enabled"])
        if "idle_clock" in updates:
            self.clock.enabled = bool(updates["idle_clock"])
        if "weather_enabled" in updates:
            self.weather.enabled = bool(updates["weather_enabled"])
        if "discord_enabled" in updates:
            self.discord.enabled = bool(updates["discord_enabled"])
        if "discord_voice_enabled" in updates:
            self.voice.enabled = bool(updates["discord_voice_enabled"])
        if "twitch_enabled" in updates:
            self.twitch.enabled = bool(updates["twitch_enabled"])
        if "game_detection_enabled" in updates:
            self.game.enabled = bool(updates["game_detection_enabled"])
        if "wow_enabled" in updates:
            self.wow.enabled = bool(updates["wow_enabled"])
        if any(k.startswith("night_") or k == "day_brightness" for k in updates):
            self.apply_night_brightness(force=True)

    def apply_night_brightness(self, force: bool = False) -> None:
        if not self.config.get("night_mode_enabled", False):
            if force and self._last_night_state is True:
                set_lan_brightness(int(self.config.get("day_brightness", 100)), ip=self.config.get("lan_ip", DEFAULT_LAN_IP))
            self._last_night_state = False
            return
        now_hhmm = time.strftime("%H:%M")
        night = is_night_time(now_hhmm, self.config.get("night_start", "23:00"), self.config.get("night_end", "07:00"))
        if force or night != self._last_night_state:
            self._last_night_state = night
            target_bri = int(self.config.get("night_brightness", 20)) if night else int(self.config.get("day_brightness", 100))
            set_lan_brightness(target_bri, ip=self.config.get("lan_ip", DEFAULT_LAN_IP))

    def trigger_test_notification(self, sender: str = "Discord", message: str = "Test! 🎮") -> None:
        self.discord.send_test_alert(sender, message)

    def get_full_status(self) -> Dict[str, Any]:
        active_plugin = self.priority_manager.get_active_plugin()
        return {
            "active_plugin": active_plugin.name if active_plugin else "none",
            "plugins": [p.get_status_info() for p in self.plugins],
            "ble": self.ble_driver.get_status(),
            "config": self.config,
        }

    async def stop_and_turn_off(self) -> None:
        """Stops the hub loop and turns off the display before exit."""
        self.running = False
        try:
            await self.ble_driver.turn_off()
        except Exception:
            pass
        await self.ble_driver.close()

    async def start(self, max_seconds: float = 0.0) -> None:
        self.running = True
        OUTPUT.mkdir(exist_ok=True)
        loop = asyncio.get_running_loop()

        # Register Windows console shutdown handler (turns off display when PC shuts down)
        try:
            import ctypes
            from ctypes import wintypes

            HandlerRoutine = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

            def _console_ctrl_handler(ctrl_type):
                # 5 = CTRL_LOGOFF_EVENT, 6 = CTRL_SHUTDOWN_EVENT
                # Do NOT trigger on 2 (CTRL_CLOSE_EVENT) so closing a launcher console window does not kill the background hub!
                if ctrl_type in (5, 6):
                    try:
                        fut = asyncio.run_coroutine_threadsafe(self.stop_and_turn_off(), loop)
                        fut.result(timeout=3.0)
                    except Exception:
                        pass
                    return True
                return False

            self._ctrl_handler_ref = HandlerRoutine(_console_ctrl_handler)
            ctypes.windll.kernel32.SetConsoleCtrlHandler(self._ctrl_handler_ref, True)
        except Exception:
            pass

        # Start web dashboard & Windows System Tray icon
        self.web_server.start()
        if not max_seconds:
            self.tray_icon = HubTrayIcon(self, loop)
            self.tray_icon.start()

        # Initialize plugins (let first upload establish the BLE link cleanly)
        for p in self.plugins:
            await p.init()

        # Background polling task
        async def poll_plugins():
            ticks = 0
            while self.running:
                for p in self.plugins:
                    try:
                        await p.poll()
                    except Exception as err:
                        print(f"Error polling {p.name}: {err}", flush=True)
                ticks += 1
                if ticks % 30 == 0:
                    self.apply_night_brightness()
                if ticks % 150 == 0:
                    trim_memory()
                await asyncio.sleep(0.4)

        poll_task = asyncio.create_task(poll_plugins())
        started_time = time.monotonic()

        print("Govee Pixel Hub running. Waiting for initial plugin state...", flush=True)
        await asyncio.sleep(1.5)
        trim_memory()

        consecutive_errors = 0
        pending_key = None
        pending_time = 0.0
        last_upload_finish = 0.0
        DEBOUNCE_SECONDS = 0.75  # Wait 750ms of track stability so rapid skips don't choke the BLE link
        MIN_UPLOAD_GAP = 0.8     # Minimum pause between uploads so H6630 flash/decoder settles

        try:
            while self.running and (not max_seconds or time.monotonic() - started_time < max_seconds):
                try:
                    active = self.priority_manager.get_active_plugin()
                    if active:
                        key = (active.name, active.get_state_key())
                        now = time.monotonic()

                        if key != self.shown_key:
                            if key != pending_key:
                                # New state detected (e.g. song skip) -> start/reset debounce timer
                                pending_key = key
                                pending_time = now
                            elif now - pending_time >= DEBOUNCE_SECONDS:
                                # State has stayed stable for DEBOUNCE_SECONDS -> check upload gap
                                if now - last_upload_finish >= MIN_UPLOAD_GAP:
                                    gif_bytes, dur = active.render()
                                    if gif_bytes:
                                        await self.ble_driver.upload(gif_bytes, label=active.name)
                                        self.shown_key = key
                                        pending_key = None
                                        last_upload_finish = time.monotonic()
                                        consecutive_errors = 0
                                        trim_memory()
                        else:
                            pending_key = None

                    await asyncio.sleep(0.1)
                except Exception as err:
                    consecutive_errors += 1
                    backoff = min(30.0, 3.0 * (2 ** (min(consecutive_errors - 1, 4))))
                    print(f"Hub loop error ({consecutive_errors}x, retrying in {backoff:.1f}s): {type(err).__name__}: {err}", flush=True)
                    self.shown_key = None
                    pending_key = None
                    last_upload_finish = time.monotonic()
                    await asyncio.sleep(backoff)
        finally:
            self.running = False
            if self.tray_icon:
                self.tray_icon.stop()
            poll_task.cancel()
            await asyncio.gather(poll_task, return_exceptions=True)
            self.web_server.stop()
            await self.voice.close()
            try:
                await self.ble_driver.turn_off()
            except Exception:
                pass
            await self.ble_driver.close()
            print("Govee Pixel Hub stopped cleanly.", flush=True)


async def main():
    setup_logging()
    lock = acquire_single_instance_lock()
    if not lock:
        print("Govee Pixel Hub laeuft bereits in einem anderen Prozess. Beende.", flush=True)
        return

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=0.0)
    args = parser.parse_args()

    PID_FILE.parent.mkdir(exist_ok=True)
    PID_FILE.write_text(json.dumps({"pid": os.getpid(), "start_time": time.time()}))

    hub = PixelHub()
    try:
        await hub.start(max_seconds=args.seconds)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"FATAL HUB ERROR: {e}", flush=True)
    finally:
        if PID_FILE.exists():
            try:
                PID_FILE.unlink()
            except Exception:
                pass


if __name__ == "__main__":
    import os
    asyncio.run(main())
