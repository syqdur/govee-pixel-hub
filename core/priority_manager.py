"""Priority and carousel manager for Govee Pixel Hub."""
import time
from typing import Any, Dict, List, Optional, Tuple

from core.plugin_base import PluginBase


class PriorityManager:
    """Selects which plugin gets the display based on priority, alerts, and idle carousel."""

    def __init__(self, plugins: List[PluginBase], config: Optional[Dict[str, Any]] = None):
        self.plugins = plugins
        self.config = config or {}
        self.carousel_seconds: float = float(self.config.get("carousel_seconds", 15.0))
        self.idle_index: int = 0
        self.last_carousel_switch: float = time.monotonic()
        self.forced_plugin: Optional[PluginBase] = None
        self.forced_until: float = 0.0

    def force_display(self, plugin_name: str, duration: float = 30.0) -> bool:
        """Manually forces a specific plugin to display for a duration."""
        target = next((p for p in self.plugins if p.name == plugin_name), None)
        if target:
            self.forced_plugin = target
            self.forced_until = time.monotonic() + duration
            return True
        return False

    def clear_force(self) -> None:
        self.forced_plugin = None
        self.forced_until = 0.0

    def get_active_plugin(self) -> Optional[PluginBase]:
        now = time.monotonic()

        # 1. Forced manual plugin (from Web UI)
        if self.forced_plugin and now < self.forced_until:
            return self.forced_plugin
        elif self.forced_plugin and now >= self.forced_until:
            self.forced_plugin = None

        # 2. High priority alerts (priority >= 80, e.g. Discord notification)
        alerts = [p for p in self.plugins if p.enabled and p.priority >= 80 and p.should_display()]
        if alerts:
            # Pick the highest priority alert
            return max(alerts, key=lambda p: p.priority)

        # 3. Active state plugins (priority 50..79, e.g. Spotify playing)
        active = [p for p in self.plugins if p.enabled and 50 <= p.priority < 80 and p.should_display()]
        if active:
            self._was_active = True
            return max(active, key=lambda p: p.priority)

        # 4. Idle carousel plugins (priority < 50, e.g. Clock, Hardware Monitor)
        idle_plugins = [p for p in self.plugins if p.enabled and p.priority < 50 and p.should_display()]
        if not idle_plugins:
            return None

        # When transitioning from active media to idle (e.g. paused music), immediately show Clock!
        if getattr(self, "_was_active", False):
            self._was_active = False
            for idx, p in enumerate(idle_plugins):
                if p.name == "clock":
                    self.idle_index = idx
                    break
            self.last_carousel_switch = now

        # Advance carousel if interval elapsed
        if now - self.last_carousel_switch >= self.carousel_seconds:
            self.idle_index = (self.idle_index + 1) % len(idle_plugins)
            self.last_carousel_switch = now

        # Ensure index in range
        self.idle_index = self.idle_index % len(idle_plugins)
        return idle_plugins[self.idle_index]

    def get_current_key(self) -> Tuple[Any, ...]:
        plugin = self.get_active_plugin()
        if not plugin:
            return ("none",)
        return (plugin.name, plugin.get_state_key())
