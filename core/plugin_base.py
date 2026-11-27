"""Base interface for Govee Pixel Hub plugins."""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple


class PluginBase(ABC):
    """Abstract base class for all display plugins.

    Priority levels:
      >= 80: High priority alert (e.g. incoming Discord message, game pop).
             Interrupts anything currently showing for a set duration.
      50-79: Active state (e.g. Media playing / Spotify).
             Shown continuously while active.
      < 50:  Idle carousel (e.g. Clock, System hardware stats, Weather).
             Rotates cyclically when no media or alert is active.
    """

    name: str = "base"
    display_name: str = "Base Plugin"
    priority: int = 10
    enabled: bool = True

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    async def init(self) -> None:
        """One-time async initialization (e.g. notification listener access)."""
        pass

    async def poll(self) -> None:
        """Periodic async update (called every 1s by the hub)."""
        pass

    def should_display(self) -> bool:
        """Whether this plugin currently has content ready to be shown."""
        return self.enabled

    def get_state_key(self) -> Any:
        """Returns a hashable state key.

        The hub compares this key to the previously displayed key; if it is
        identical, no new GIF upload is performed (saving BLE bandwidth and avoiding re-renders).
        """
        return None

    @abstractmethod
    def render(self) -> Tuple[bytes, float]:
        """Renders the scene into a looping 32x32 GIF.

        Returns (gif_bytes, loop_duration_seconds).
        """
        pass

    def get_status_info(self) -> Dict[str, Any]:
        """Returns plugin status for the Web UI API."""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "priority": self.priority,
            "enabled": self.enabled,
            "active": self.should_display(),
        }
