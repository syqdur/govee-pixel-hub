"""Spotify and Windows Media session plugin."""
import asyncio
import datetime
import hashlib
import io
import time
from typing import Any, Dict, Optional, Tuple

from PIL import Image, ImageOps
from core.plugin_base import PluginBase
import scenes


class SpotifyPlugin(PluginBase):
    name = "spotify"
    display_name = "Spotify & Media"
    enabled = True

    @property
    def priority(self) -> int:
        if self.media_state:
            _, _, playing, _ = self.media_state
            if playing:
                return 60
            return 45
        return 45

    def __init__(self, config: Optional[Dict[str, Any]] = None, discord_plugin=None, weather_plugin=None):
        super().__init__(config)
        self.discord_plugin = discord_plugin
        self.weather_plugin = weather_plugin
        self.media_state = None  # (track, thumbnail, playing, timeline)
        self.last_track_key = None
        self._manager = None
        self._cached_track_key = None
        self._cached_thumbnail = None

    async def poll(self) -> None:
        try:
            from winrt.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as Manager,
                GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status,
            )
            from winrt.windows.storage.streams import DataReader

            if not self._manager:
                self._manager = await Manager.request_async()
            manager = self._manager
            apps = self.config.get("media_apps", ["spotify"])

            found_session = None
            try:
                sessions = manager.get_sessions()
            except Exception:
                self._manager = await Manager.request_async()
                sessions = self._manager.get_sessions()

            for session in sessions:
                app_id = session.source_app_user_model_id.lower()
                if any(a.lower() in app_id for a in apps):
                    found_session = session
                    break

            if not found_session:
                self.media_state = None
                return

            props = await found_session.try_get_media_properties_async()
            if not props or not props.title:
                self.media_state = None
                return

            playing = found_session.get_playback_info().playback_status == Status.PLAYING

            current_key = (props.title, props.artist or "", props.album_title or "")
            if current_key == self._cached_track_key and self._cached_thumbnail is not None:
                thumbnail_data = self._cached_thumbnail
            else:
                # When track changes, give Windows Media a brief moment to update its thumbnail stream
                if current_key != self._cached_track_key:
                    await asyncio.sleep(0.15)
                    try:
                        updated_props = await found_session.try_get_media_properties_async()
                        if updated_props and updated_props.title == props.title:
                            props = updated_props
                    except Exception:
                        pass

                thumbnail_data = None
                if props.thumbnail:
                    try:
                        stream = await props.thumbnail.open_read_async()
                        reader = DataReader(stream)
                        try:
                            if stream.size <= 20_000_000:
                                await reader.load_async(stream.size)
                                raw_bytes = bytearray(stream.size)
                                reader.read_bytes(raw_bytes)
                                # Pre-downsample to 20x20 thumbnail bytes to keep RAM ultra low
                                with Image.open(io.BytesIO(raw_bytes)) as orig:
                                    buf = io.BytesIO()
                                    ImageOps.fit(orig.convert("RGB"), (20, 20), method=Image.Resampling.LANCZOS).save(buf, format="PNG")
                                    thumbnail_data = buf.getvalue()
                        finally:
                            reader.close()
                            stream.close()
                    except Exception:
                        thumbnail_data = None
                self._cached_track_key = current_key
                self._cached_thumbnail = thumbnail_data

            timeline = None
            try:
                tl = found_session.get_timeline_properties()
                if tl and tl.end_time.total_seconds() > 0:
                    timeline = (tl.position.total_seconds(), tl.end_time.total_seconds())
            except Exception:
                pass

            track = {
                "title": props.title,
                "artist": props.artist or "",
                "album": props.album_title or "",
            }
            self.media_state = (track, thumbnail_data, playing, timeline)
        except Exception as err:
            self.media_state = None

    def should_display(self) -> bool:
        if not self.enabled or not self.media_state:
            return False
        _, _, playing, _ = self.media_state
        if not playing and not self.config.get("show_paused_spotify", False):
            return False
        return True

    def get_state_key(self) -> Any:
        if not self.media_state:
            return None
        track, thumbnail, playing, timeline = self.media_state
        thumb_hash = hashlib.md5(thumbnail).hexdigest()[:8] if thumbnail else None
        speed = self.config.get("text_speed_ms", 75)
        hold = self.config.get("text_hold_ms", 1200)
        show_eq = bool(self.config.get("spotify_eq", False))
        text_mode = self.config.get("spotify_text_mode", "pages")
        font_mini = bool(self.config.get("spotify_font_mini", False) or self.config.get("spotify_font_size") == "mini")
        ambient_breath = bool(self.config.get("spotify_ambient_breath", True))
        weather_key = (
            (self.weather_plugin.weather_data.get("temp"), self.weather_plugin.weather_data.get("icon"))
            if (self.weather_plugin and self.weather_plugin.weather_data and self.config.get("spotify_show_weather", True))
            else None
        )
        # To eliminate any black screen flashing during playback, do not re-upload
        # for minute ticks or progress ticks unless explicitly configured.
        clock_key = (
            datetime.datetime.now().strftime("%H:%M")
            if bool(self.config.get("spotify_mini_clock", False))
            else None
        )
        sync_sec = int(self.config.get("progress_sync_seconds", 0))
        progress_key = (
            int(timeline[0] // sync_sec)
            if (sync_sec > 0 and playing and timeline and timeline[1] > 0)
            else None
        )
        return (self.name, track.get("title"), track.get("artist"), thumb_hash, playing, speed, hold, show_eq, text_mode, font_mini, ambient_breath, weather_key, clock_key, progress_key)

    def render(self) -> Tuple[bytes, float]:
        if not self.media_state:
            return b"", 0.0
        track, thumbnail, playing, timeline = self.media_state
        weather_data = (
            self.weather_plugin.weather_data
            if (self.weather_plugin and self.weather_plugin.weather_data and self.config.get("spotify_show_weather", True))
            else None
        )
        gif_bytes = scenes.spotify_scene(
            track,
            thumbnail,
            playing=playing,
            timeline=timeline,
            options=self.config,
            weather=weather_data,
        )
        return gif_bytes, 10.0

    def get_status_info(self) -> Dict[str, Any]:
        info = super().get_status_info()
        if self.media_state:
            track, _, playing, timeline = self.media_state
            info.update({
                "title": track.get("title"),
                "artist": track.get("artist"),
                "playing": playing,
                "progress_seconds": timeline[0] if timeline else None,
                "duration_seconds": timeline[1] if timeline else None,
            })
        else:
            info.update({"title": None, "artist": None, "playing": False})
        return info
