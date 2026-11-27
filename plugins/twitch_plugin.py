"""Twitch Live-Alert plugin (no API key required)."""
import asyncio
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Set, Tuple

from core.plugin_base import PluginBase
import scenes


class TwitchPlugin(PluginBase):
    name = "twitch"
    display_name = "Twitch Live-Alerts"
    priority = 98
    enabled = True

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.check_interval: float = 120.0
        self.last_check: float = 0.0
        self.live_channels: Set[str] = set()
        self.initialized_channels: bool = False
        self.current_alert: Optional[Tuple[str, str]] = None  # (streamer, game)
        self.alert_until: float = 0.0

    def _get_channels(self) -> List[str]:
        raw = self.config.get("twitch_channels", [])
        if isinstance(raw, str):
            raw = [c.strip() for c in raw.split(",") if c.strip()]
        return [str(c).strip().lower() for c in raw if str(c).strip()]

    def trigger_test_alert(self, streamer: str = "Streamer", game: str = "LIVE!") -> None:
        self.current_alert = (streamer, game)
        self.alert_until = time.monotonic() + 12.0

    async def _check_channel(self, channel: str) -> Tuple[bool, str]:
        """Checks whether a Twitch channel is live via decapi.me (zero auth required)."""
        def fetch():
            q = urllib.parse.quote(channel)
            req = urllib.request.Request(
                f"https://decapi.me/twitch/uptime/{q}",
                headers={"User-Agent": "GoveePixelHub/1.0"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                txt = resp.read().decode("utf-8", errors="ignore").strip().lower()
            is_live = bool(txt) and ("offline" not in txt) and ("error" not in txt) and ("not found" not in txt)
            game = ""
            if is_live:
                try:
                    req_g = urllib.request.Request(
                        f"https://decapi.me/twitch/game/{q}",
                        headers={"User-Agent": "GoveePixelHub/1.0"},
                    )
                    with urllib.request.urlopen(req_g, timeout=4) as resp_g:
                        game = resp_g.read().decode("utf-8", errors="ignore").strip()
                except Exception:
                    game = "LIVE"
            return is_live, game

        try:
            return await asyncio.to_thread(fetch)
        except Exception:
            return False, ""

    async def poll(self) -> None:
        now = time.monotonic()
        if self.current_alert and now >= self.alert_until:
            self.current_alert = None

        if not self.enabled:
            return

        channels = self._get_channels()
        if not channels:
            return

        if now - self.last_check < self.check_interval:
            return
        self.last_check = now

        new_live: Set[str] = set()
        for ch in channels[:6]:  # Cap to 6 channels to keep background HTTP minimal
            is_live, game = await self._check_channel(ch)
            if is_live:
                new_live.add(ch)
                if self.initialized_channels and ch not in self.live_channels:
                    self.current_alert = (ch, game or "LIVE")
                    self.alert_until = time.monotonic() + 15.0

        self.live_channels = new_live
        self.initialized_channels = True

    def should_display(self) -> bool:
        return self.enabled and self.current_alert is not None and time.monotonic() < self.alert_until

    def get_state_key(self) -> Any:
        if not self.should_display():
            return None
        return (self.name, self.current_alert)

    def render(self) -> Tuple[bytes, float]:
        if not self.current_alert:
            return b"", 0.0
        streamer, game = self.current_alert
        gif_bytes = scenes.twitch_live_scene(streamer, game)
        return gif_bytes, 12.0

    def get_status_info(self) -> Dict[str, Any]:
        info = super().get_status_info()
        info.update({
            "channels": self._get_channels(),
            "live_channels": sorted(self.live_channels),
        })
        return info
