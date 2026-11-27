"""Desktop Digital Clock & Calendar plugin."""
import time
from typing import Any, Dict, Optional, Tuple

from core.lan_control import is_night_time
from core.plugin_base import PluginBase
import scenes


class ClockPlugin(PluginBase):
    name = "clock"
    display_name = "Desktop Clock"
    priority = 10
    enabled = True

    def __init__(self, config: Optional[Dict[str, Any]] = None, discord_plugin=None, weather_plugin=None):
        super().__init__(config)
        self.discord_plugin = discord_plugin
        self.weather_plugin = weather_plugin

    def should_display(self) -> bool:
        return self.enabled

    def _effective_options(self) -> Dict[str, Any]:
        opts = dict(self.config)
        if opts.get("night_mode_enabled", False):
            now_hhmm = time.strftime("%H:%M")
            if is_night_time(now_hhmm, opts.get("night_start", "23:00"), opts.get("night_end", "07:00")):
                opts["clock_theme"] = opts.get("night_theme", "fire")
        return opts

    def get_state_key(self) -> Any:
        unread = self.discord_plugin.unread_count if self.discord_plugin else 0
        minute_tag = time.strftime("%H:%M")
        opts = self._effective_options()
        color = opts.get("clock_color", "#00e5ff")
        theme = opts.get("clock_theme", "auto")
        style = opts.get("clock_style", "digital")
        flip_style = opts.get("flip_style", "horizontal")
        weather_tag = (
            (self.weather_plugin.weather_data.get("temp"), self.weather_plugin.weather_data.get("icon"))
            if (self.weather_plugin and self.weather_plugin.weather_data and opts.get("weather_enabled", True))
            else None
        )
        return (self.name, minute_tag, unread, color, theme, style, flip_style, weather_tag)

    def render(self) -> Tuple[bytes, float]:
        unread = self.discord_plugin.unread_count if self.discord_plugin else 0
        opts = self._effective_options()
        style = opts.get("clock_style", "digital")
        weather_data = (
            self.weather_plugin.weather_data
            if (self.weather_plugin and self.weather_plugin.weather_data and opts.get("weather_enabled", True))
            else None
        )
        if style == "flip":
            gif_bytes = scenes.flip_clock_scene(
                unread=unread, weather_data=weather_data, options=opts
            )
        else:
            gif_bytes = scenes.idle_scene(
                unread=unread, weather_data=weather_data, options=opts
            )
        return gif_bytes, 2.0

    def get_status_info(self) -> Dict[str, Any]:
        info = super().get_status_info()
        info.update({
            "current_time": time.strftime("%H:%M"),
            "current_date": time.strftime("%d.%m.%Y"),
            "clock_color": self.config.get("clock_color", "#00e5ff"),
            "clock_style": self.config.get("clock_style", "flip"),
            "flip_style": self.config.get("flip_style", "horizontal"),
        })
        return info
