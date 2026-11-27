"""Windows Hardware Monitor (CPU & RAM) plugin."""
import ctypes
import time
from typing import Any, Dict, Optional, Tuple

from PIL import Image, ImageDraw

from core.plugin_base import PluginBase
import pixel_font
import scenes


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLow", ctypes.c_uint32), ("dwHigh", ctypes.c_uint32)]

    def val(self) -> int:
        return (self.dwHigh << 32) | self.dwLow


class HardwarePlugin(PluginBase):
    name = "hardware"
    display_name = "Hardware Monitor"
    priority = 10
    enabled = True

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.cpu_percent: int = 0
        self.ram_percent: int = 0
        self.last_cpu_time = None
        self.last_kernel = None
        self.last_user = None

    def _query_ram(self) -> int:
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return int(stat.dwMemoryLoad)
        return 0

    def _query_cpu(self) -> int:
        idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        ):
            return 0
        i, k, u = idle.val(), kernel.val(), user.val()
        if self.last_cpu_time is None:
            self.last_cpu_time, self.last_kernel, self.last_user = i, k, u
            return 0

        diff_idle = i - self.last_cpu_time
        diff_total = (k - self.last_kernel) + (u - self.last_user)
        self.last_cpu_time, self.last_kernel, self.last_user = i, k, u

        if diff_total > 0:
            load = int(100.0 * (diff_total - diff_idle) / diff_total)
            return max(0, min(100, load))
        return 0

    async def poll(self) -> None:
        self.ram_percent = self._query_ram()
        self.cpu_percent = self._query_cpu()

    def should_display(self) -> bool:
        return self.enabled

    def get_state_key(self) -> Any:
        # Quantize percentages to 5% steps so minor fluctuations don't trigger constant uploads
        cpu_q = (self.cpu_percent // 5) * 5
        ram_q = (self.ram_percent // 5) * 5
        return (self.name, cpu_q, ram_q)

    def render(self) -> Tuple[bytes, float]:
        image = Image.new("RGB", (32, 32), "black")
        draw = ImageDraw.Draw(image)

        # Top header
        draw.rectangle((0, 0, 31, 7), fill="#121e2d")
        pixel_font.draw_text(image, (3, 1), "SYS MONITOR", fill="#00e5ff", font_type="mini")

        # CPU section
        draw.rectangle((1, 9, 8, 14), fill="#1a1a1a")
        pixel_font.draw_text(image, (2, 9), "CPU", fill="#ffffff", font_type="mini")
        cpu_str = f"{self.cpu_percent}%"
        cpu_col = "#00e676" if self.cpu_percent < 75 else ("#ffb300" if self.cpu_percent < 88 else "#ff5252")
        pixel_font.draw_text(
            image, (31 - pixel_font.measure_text(cpu_str, "mini"), 9), cpu_str, fill=cpu_col, font_type="mini"
        )
        # CPU bar at y=15..17
        draw.rectangle((1, 15, 30, 17), fill="#222222")
        w_cpu = int(29 * max(0, min(100, self.cpu_percent)) / 100)
        if w_cpu > 0:
            draw.rectangle((1, 15, 1 + w_cpu, 17), fill=cpu_col)

        # RAM section
        draw.rectangle((1, 20, 8, 25), fill="#1a1a1a")
        pixel_font.draw_text(image, (2, 20), "RAM", fill="#ffffff", font_type="mini")
        ram_str = f"{self.ram_percent}%"
        ram_col = "#00e5ff" if self.ram_percent < 80 else ("#ffb300" if self.ram_percent < 90 else "#ff5252")
        pixel_font.draw_text(
            image, (31 - pixel_font.measure_text(ram_str, "mini"), 20), ram_str, fill=ram_col, font_type="mini"
        )
        # RAM bar at y=26..28
        draw.rectangle((1, 26, 30, 28), fill="#222222")
        w_ram = int(29 * max(0, min(100, self.ram_percent)) / 100)
        if w_ram > 0:
            draw.rectangle((1, 26, 1 + w_ram, 28), fill=ram_col)

        # Encode single or 2-frame GIF
        gif_bytes = scenes._encode([image], [2000])
        return gif_bytes, 4.0

    def get_status_info(self) -> Dict[str, Any]:
        info = super().get_status_info()
        info.update({
            "cpu_percent": self.cpu_percent,
            "ram_percent": self.ram_percent,
        })
        return info
