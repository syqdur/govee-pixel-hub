"""Auto-Game-Detection plugin for popular PC games."""
import time
from typing import Any, Dict, Optional, Tuple

import psutil
from core.plugin_base import PluginBase
import scenes

KNOWN_GAMES: Dict[str, Tuple[str, str]] = {
    "wow.exe": ("WoW", "#ffb300"),
    "wowclassic.exe": ("WoW Classic", "#ffb300"),
    "cs2.exe": ("CS2", "#ff8f00"),
    "valorant-win64-shipping.exe": ("Valorant", "#ff4655"),
    "league of legends.exe": ("LoL", "#00bcd4"),
    "overwatch.exe": ("Overwatch", "#fa9c1e"),
    "eldenring.exe": ("Elden Ring", "#eab308"),
    "gta5.exe": ("GTA V", "#1ed760"),
    "cyberpunk2077.exe": ("Cyberpunk", "#facc15"),
    "fortniteclient-win64-shipping.exe": ("Fortnite", "#38bdf8"),
    "rocketleague.exe": ("Rocket League", "#3b82f6"),
    "dota2.exe": ("Dota 2", "#ef4444"),
    "r5apex.exe": ("Apex", "#ef4444"),
    "apex_dx12.exe": ("Apex", "#ef4444"),
    "bg3.exe": ("BG3", "#c084fc"),
    "bg3_dx11.exe": ("BG3", "#c084fc"),
    "diablo iv.exe": ("Diablo IV", "#dc2626"),
    "helldivers2.exe": ("Helldivers 2", "#facc15"),
    "escapefromtarkov.exe": ("Tarkov", "#a3e635"),
    "minecraft.windows.exe": ("Minecraft", "#22c55e"),
}


class GamePlugin(PluginBase):
    name = "game"
    display_name = "Game Detection"
    priority = 55
    enabled = True

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.active_game: Optional[str] = None
        self.accent_color: str = "#00e5ff"
        self.started_at: float = 0.0
        self.last_scan: float = 0.0
        self.scan_interval: float = 5.0

    def detect_running_game(self) -> Optional[Tuple[str, str]]:
        """Scans running processes for known games."""
        try:
            for proc in psutil.process_iter(["name"]):
                pname = (proc.info.get("name") or "").lower()
                if pname in KNOWN_GAMES:
                    return KNOWN_GAMES[pname]
        except Exception:
            pass
        return None

    async def poll(self) -> None:
        if not self.enabled:
            self.active_game = None
            return
        now = time.monotonic()
        if now - self.last_scan < self.scan_interval:
            return
        self.last_scan = now

        found = self.detect_running_game()
        if found:
            game_name, color = found
            if game_name != self.active_game:
                self.active_game = game_name
                self.accent_color = color
                self.started_at = now
        else:
            self.active_game = None
            self.started_at = 0.0

    def should_display(self) -> bool:
        return self.enabled and self.active_game is not None

    def get_state_key(self) -> Any:
        if not self.should_display():
            return None
        mins = int((time.monotonic() - self.started_at) // 300)  # Update every 5 min to keep BLE quiet
        cpu = int(psutil.cpu_percent(interval=None) // 20)
        return (self.name, self.active_game, mins, cpu)

    def render(self) -> Tuple[bytes, float]:
        if not self.active_game:
            return b"", 0.0
        elapsed_min = max(0, int((time.monotonic() - self.started_at) // 60))
        cpu = int(round(psutil.cpu_percent(interval=None)))
        gif_bytes = scenes.game_scene(
            self.active_game,
            accent=self.accent_color,
            elapsed_min=elapsed_min,
            cpu_percent=cpu,
        )
        return gif_bytes, 10.0

    def get_status_info(self) -> Dict[str, Any]:
        info = super().get_status_info()
        elapsed_min = max(0, int((time.monotonic() - self.started_at) // 60)) if self.active_game else 0
        info.update({
            "active_game": self.active_game,
            "elapsed_minutes": elapsed_min,
        })
        return info
