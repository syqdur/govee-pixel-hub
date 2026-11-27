"""Open-Meteo local weather plugin for Govee Pixel Hub."""
import asyncio
import json
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

from core.plugin_base import PluginBase
import scenes

WMO_CONDITIONS = {
    0: ("Klar", "Sonnig", "sun"),
    1: ("Überwiegend klar", "Heiter", "partly_cloudy"),
    2: ("Teilweise bewölkt", "Teilweise bewölkt", "partly_cloudy"),
    3: ("Bedeckt", "Bedeckt", "cloud"),
    45: ("Nebel", "Nebel", "fog"),
    48: ("Reifnebel", "Reifnebel", "fog"),
    51: ("Leichter Nieselregen", "Leichter Nieselregen", "rain"),
    53: ("Nieselregen", "Nieselregen", "rain"),
    55: ("Dichter Nieselregen", "Dichter Nieselregen", "rain"),
    61: ("Leichter Regen", "Leichter Regen", "rain"),
    63: ("Mäßiger Regen", "Mäßiger Regen", "rain"),
    65: ("Starker Regen", "Starker Regen", "rain"),
    71: ("Leichter Schneefall", "Leichter Schneefall", "snow"),
    73: ("Mäßiger Schneefall", "Mäßiger Schneefall", "snow"),
    75: ("Starker Schneefall", "Starker Schneefall", "snow"),
    77: ("Schneegriesel", "Schneegriesel", "snow"),
    80: ("Leichter Schauer", "Leichter Schauer", "rain"),
    81: ("Mäßiger Schauer", "Mäßiger Schauer", "rain"),
    82: ("Heftiger Schauer", "Heftiger Schauer", "rain"),
    85: ("Leichter Schneeschauer", "Leichter Schneeschauer", "snow"),
    86: ("Starker Schneeschauer", "Starker Schneeschauer", "snow"),
    95: ("Gewitter", "Gewitter", "thunder"),
    96: ("Gewitter mit Hagel", "Gewitter mit Hagel", "thunder"),
    99: ("Schweres Gewitter", "Schweres Gewitter", "thunder"),
}


class WeatherPlugin(PluginBase):
    name = "weather"
    display_name = "Wetter & Temperatur"
    priority = 10
    enabled = True

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.city: str = self.config.get("weather_city", "Berlin")
        self.latitude: float = float(self.config.get("weather_lat", 52.5244))
        self.longitude: float = float(self.config.get("weather_lon", 13.4105))
        self.weather_data: Optional[Dict[str, Any]] = None
        self.last_fetch: float = 0.0
        self.fetch_interval: float = 900.0  # 15 minutes

    async def init(self) -> None:
        await self._resolve_city_coords()
        await self._fetch_weather()

    async def _resolve_city_coords(self) -> None:
        """Looks up coordinates for the configured city name if needed."""
        target_city = self.config.get("weather_city", self.city)
        if not target_city:
            return
        try:
            def lookup():
                q = urllib.parse.quote(target_city)
                url = f"https://geocoding-api.open-meteo.com/v1/search?name={q}&count=1&language=de&format=json"
                req = urllib.request.Request(url, headers={"User-Agent": "GoveePixelHub/1.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    results = data.get("results")
                    if results:
                        return results[0]
                return None

            res = await asyncio.to_thread(lookup)
            if res:
                self.city = res.get("name", target_city)
                self.latitude = float(res.get("latitude", self.latitude))
                self.longitude = float(res.get("longitude", self.longitude))
        except Exception as err:
            pass

    async def _fetch_weather(self) -> None:
        """Fetches current weather and today's min/max from Open-Meteo."""
        try:
            def fetch():
                url = (
                    f"https://api.open-meteo.com/v1/forecast"
                    f"?latitude={self.latitude}&longitude={self.longitude}"
                    f"&current=temperature_2m,weather_code,is_day"
                    f"&daily=temperature_2m_max,temperature_2m_min"
                    f"&timezone=auto"
                )
                req = urllib.request.Request(url, headers={"User-Agent": "GoveePixelHub/1.0"})
                with urllib.request.urlopen(req, timeout=6) as resp:
                    return json.loads(resp.read().decode("utf-8"))

            raw = await asyncio.to_thread(fetch)
            cur = raw.get("current", {})
            daily = raw.get("daily", {})

            temp = round(float(cur.get("temperature_2m", 0)))
            code = int(cur.get("weather_code", 0))
            is_day = bool(cur.get("is_day", 1))

            night_desc, day_desc, icon_type = WMO_CONDITIONS.get(code, ("Unbekannt", "Unbekannt", "cloud"))
            condition = day_desc if is_day else night_desc
            if icon_type == "sun" and not is_day:
                icon_type = "moon"

            t_max = round(float(daily.get("temperature_2m_max", [temp])[0]))
            t_min = round(float(daily.get("temperature_2m_min", [temp])[0]))

            self.weather_data = {
                "city": self.city,
                "temp": temp,
                "code": code,
                "is_day": is_day,
                "icon": icon_type,
                "condition": condition,
                "temp_max": t_max,
                "temp_min": t_min,
                "updated_at": time.time(),
            }
            self.last_fetch = time.monotonic()
        except Exception as err:
            pass

    async def poll(self) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        # If city changed in config
        current_cfg_city = self.config.get("weather_city", self.city)
        if current_cfg_city.lower() != self.city.lower():
            await self._resolve_city_coords()
            await self._fetch_weather()
            return

        if now - self.last_fetch >= self.fetch_interval or self.weather_data is None:
            await self._fetch_weather()

    def should_display(self) -> bool:
        return self.enabled and self.weather_data is not None and bool(self.config.get("weather_carousel", False))

    def get_state_key(self) -> Any:
        if not self.weather_data:
            return None
        return (
            self.name,
            self.weather_data.get("city"),
            self.weather_data.get("temp"),
            self.weather_data.get("code"),
            self.weather_data.get("is_day"),
        )

    def render(self) -> Tuple[bytes, float]:
        if not self.weather_data:
            return b"", 0.0
        return scenes.weather_scene(self.weather_data, options=self.config)

    def get_status_info(self) -> Dict[str, Any]:
        info = super().get_status_info()
        if self.weather_data:
            info.update({
                "city": self.weather_data.get("city"),
                "temp": self.weather_data.get("temp"),
                "temp_max": self.weather_data.get("temp_max"),
                "temp_min": self.weather_data.get("temp_min"),
                "condition": self.weather_data.get("condition"),
                "icon": self.weather_data.get("icon"),
                "is_day": self.weather_data.get("is_day"),
            })
        else:
            info.update({"city": self.city, "temp": None, "condition": "Lädt..."})
        return info
