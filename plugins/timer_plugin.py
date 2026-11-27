"""Focus, Pomodoro & Gaming Timer plugin."""
import math
import time
from typing import Any, Dict, Optional, Tuple

from core.plugin_base import PluginBase
import scenes


class TimerPlugin(PluginBase):
    name = "timer"
    display_name = "Fokus & Pomodoro Timer"
    enabled = True

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.running: bool = False
        self.total_seconds: float = 0.0
        self.end_time: float = 0.0
        self.finished_until: float = 0.0
        self.label: str = "FOKUS"

    @property
    def priority(self) -> int:
        now = time.monotonic()
        if self.finished_until > now:
            return 95
        if self.running:
            return 70
        return 10

    def start_timer(self, minutes: float = 25.0, label: str = "FOKUS") -> None:
        secs = max(10.0, float(minutes) * 60.0)
        self.total_seconds = secs
        self.end_time = time.monotonic() + secs
        self.finished_until = 0.0
        self.label = (label or "FOKUS").strip()[:8].upper()
        self.running = True

    def stop_timer(self) -> None:
        self.running = False
        self.finished_until = 0.0

    def remaining_seconds(self) -> float:
        if not self.running:
            return 0.0
        return max(0.0, self.end_time - time.monotonic())

    async def poll(self) -> None:
        if self.running and time.monotonic() >= self.end_time:
            self.running = False
            self.finished_until = time.monotonic() + 12.0

    def should_display(self) -> bool:
        now = time.monotonic()
        return self.enabled and (self.running or self.finished_until > now)

    def get_state_key(self) -> Any:
        now = time.monotonic()
        if self.finished_until > now:
            return (self.name, "done", self.label)
        if not self.running:
            return None
        rem = max(0.0, self.end_time - now)
        bucket = ("m", int(math.ceil(rem / 60.0))) if rem > 60 else ("s", int(math.ceil(rem / 15.0)))
        return (self.name, "run", self.label, bucket, int(self.total_seconds))

    def render(self) -> Tuple[bytes, float]:
        now = time.monotonic()
        finished = self.finished_until > now
        rem = 0.0 if finished else self.remaining_seconds()
        gif_bytes = scenes.timer_scene(
            remaining_sec=rem,
            total_sec=self.total_seconds or 1.0,
            label=self.label,
            finished=finished,
        )
        return gif_bytes, 10.0

    def get_status_info(self) -> Dict[str, Any]:
        info = super().get_status_info()
        now = time.monotonic()
        info.update({
            "running": self.running,
            "finished": self.finished_until > now,
            "remaining_seconds": int(round(self.remaining_seconds())),
            "total_seconds": int(round(self.total_seconds)),
            "label": self.label,
        })
        return info
