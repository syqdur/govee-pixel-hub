"""World of Warcraft Character Stats plugin (reads GoveePixelStats SavedVariables)."""
from pathlib import Path
import re
import time
from typing import Any, Dict, Optional, Tuple

import psutil
from core.plugin_base import PluginBase
import scenes

WOW_DEFAULT_ROOT = Path(r"C:\Program Files (x86)\World of Warcraft")
WOW_PROCESS_NAMES = {"wow.exe", "wowclassic.exe", "wowt.exe", "wowb.exe"}


def parse_wow_saved_variables(text: str) -> Dict[str, Any]:
    """Parses GoveePixelStatsDB Lua table into a Python dict."""
    data: Dict[str, Any] = {}
    for m in re.finditer(r'\["([^"]+)"\]\s*=\s*(?:"([^"]*)"|([-+]?\d+(?:\.\d+)?))', text):
        key = m.group(1)
        if m.group(2) is not None:
            data[key] = m.group(2)
        elif m.group(3) is not None:
            raw_num = m.group(3)
            data[key] = float(raw_num) if "." in raw_num else int(raw_num)
    return data


class WoWPlugin(PluginBase):
    name = "wow"
    display_name = "WoW Charakter-HUD"
    priority = 58
    enabled = True

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.stats: Optional[Dict[str, Any]] = None
        self.last_mtime: float = 0.0
        self.last_scan: float = 0.0
        self.scan_interval: float = 5.0
        self.wow_is_running: bool = False

    def _find_latest_saved_vars(self) -> Optional[Path]:
        root = Path(self.config.get("wow_path", str(WOW_DEFAULT_ROOT)))
        if not root.exists():
            return None
        candidates = list(root.glob("_*/WTF/Account/*/SavedVariables/GoveePixelStats.lua"))
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.stat().st_mtime)

    def _check_wow_running(self) -> bool:
        try:
            for proc in psutil.process_iter(["name"]):
                if (proc.info.get("name") or "").lower() in WOW_PROCESS_NAMES:
                    return True
        except Exception:
            pass
        return False

    async def poll(self) -> None:
        if not self.enabled:
            self.wow_is_running = False
            return
        now = time.monotonic()
        if now - self.last_scan < self.scan_interval:
            return
        self.last_scan = now

        self.wow_is_running = self._check_wow_running()
        sv_path = self._find_latest_saved_vars()
        if sv_path and sv_path.exists():
            try:
                mtime = sv_path.stat().st_mtime
                if mtime != self.last_mtime or self.stats is None:
                    text = sv_path.read_text(encoding="utf-8", errors="ignore")
                    parsed = parse_wow_saved_variables(text)
                    if parsed.get("name"):
                        self.stats = parsed
                        self.last_mtime = mtime
            except Exception:
                pass

    def should_display(self) -> bool:
        return self.enabled and self.wow_is_running and self.stats is not None

    def get_state_key(self) -> Any:
        if not self.should_display() or not self.stats:
            return None
        return (
            self.name,
            self.stats.get("name"),
            self.stats.get("level"),
            self.stats.get("ilvl"),
            self.stats.get("crit"),
            self.stats.get("haste"),
            self.stats.get("mastery"),
            self.stats.get("vers"),
            self.stats.get("gold"),
            self.stats.get("zone"),
        )

    def render(self) -> Tuple[bytes, float]:
        demo = self.stats or {
            "name": "Hero",
            "class": "WARRIOR",
            "spec": "Fury",
            "level": 80,
            "ilvl": 635,
            "crit": 28.4,
            "haste": 19.2,
            "mastery": 42.0,
            "vers": 8.5,
            "gold": 124500,
            "zone": "Azeroth",
        }
        gif_bytes = scenes.wow_scene(demo)
        return gif_bytes, 10.0

    def get_status_info(self) -> Dict[str, Any]:
        info = super().get_status_info()
        info.update({
            "wow_running": self.wow_is_running,
            "stats": self.stats,
        })
        return info
