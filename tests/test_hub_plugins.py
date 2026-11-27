"""Tests for Hub plugins and Priority Manager."""
import unittest
from core.priority_manager import PriorityManager
from plugins.clock_plugin import ClockPlugin
from plugins.discord_plugin import DiscordPlugin
from plugins.hardware_plugin import HardwarePlugin
from plugins.spotify_plugin import SpotifyPlugin
from plugins.discord_voice_plugin import DiscordVoicePlugin
from plugins.weather_plugin import WeatherPlugin
import scenes


class HubPluginTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "notify_apps": ["Discord"],
            "notify_min_seconds": 10,
            "carousel_seconds": 15,
            "clock_color": "#00e5ff",
        }
        self.discord = DiscordPlugin(self.config)
        self.spotify = SpotifyPlugin(self.config, discord_plugin=self.discord)
        self.clock = ClockPlugin(self.config, discord_plugin=self.discord)
        self.hardware = HardwarePlugin(self.config)
        self.plugins = [self.discord, self.spotify, self.clock, self.hardware]
        self.mgr = PriorityManager(self.plugins, self.config)

    def test_default_idle_is_clock(self):
        # With no media and no discord alerts, active should be an idle plugin
        active = self.mgr.get_active_plugin()
        self.assertIn(active.name, ("clock", "hardware"))

    def test_alert_overrides_everything(self):
        # Inject an alert
        self.discord.send_test_alert("Max", "Dungeon Pop!")
        self.assertTrue(self.discord.should_display())
        active = self.mgr.get_active_plugin()
        self.assertEqual(active.name, "discord")

    def test_clock_render(self):
        gif_bytes, dur = self.clock.render()
        self.assertGreater(len(gif_bytes), 200)
        self.assertTrue(gif_bytes.startswith(b"GIF89a"))

    def test_hardware_render(self):
        self.hardware.cpu_percent = 42
        self.hardware.ram_percent = 65
        gif_bytes, dur = self.hardware.render()
        self.assertGreater(len(gif_bytes), 200)
        self.assertTrue(gif_bytes.startswith(b"GIF89a"))

    def test_discord_alert_render(self):
        self.discord.send_test_alert("Alex", "Lust auf Gaming? 🎮")
        gif_bytes, dur = self.discord.render()
        self.assertGreater(len(gif_bytes), 500)
        self.assertTrue(gif_bytes.startswith(b"GIF89a"))

    def test_voice_does_not_interrupt_playing_spotify(self):
        # Configure voice and spotify
        voice = DiscordVoicePlugin(self.config)
        voice.channel_id = "123456"
        voice.speaking_users.add("user1")
        self.assertTrue(voice.should_display())

        # Spotify is playing
        self.spotify.media_state = ({"title": "Song", "artist": "Artist"}, None, True, (10, 100))
        self.assertTrue(self.spotify.should_display())
        self.assertEqual(self.spotify.priority, 60)
        self.assertEqual(voice.priority, 50)

        mgr = PriorityManager([self.discord, voice, self.spotify, self.clock, self.hardware], self.config)
        active = mgr.get_active_plugin()
        self.assertEqual(active.name, "spotify")  # Spotify takes precedence!

    def test_voice_interrupts_when_paused_or_explicitly_configured(self):
        voice = DiscordVoicePlugin(self.config)
        voice.channel_id = "123456"
        voice.speaking_users.add("user1")

        # When Spotify is paused
        self.spotify.media_state = ({"title": "Song", "artist": "Artist"}, None, False, (10, 100))
        self.assertEqual(self.spotify.priority, 45)
        self.assertEqual(voice.priority, 50)

        mgr = PriorityManager([self.discord, voice, self.spotify, self.clock, self.hardware], self.config)
        active = mgr.get_active_plugin()
        self.assertEqual(active.name, "discord_voice")

        # When voice_interrupts_music is True, voice overrides even playing music
        cfg_override = dict(self.config)
        cfg_override["voice_interrupts_music"] = True
        voice_override = DiscordVoicePlugin(cfg_override)
        voice_override.channel_id = "123456"
        voice_override.speaking_users.add("user1")
        self.assertEqual(voice_override.priority, 70)

        self.spotify.media_state = ({"title": "Song", "artist": "Artist"}, None, True, (10, 100))
        mgr2 = PriorityManager([self.discord, voice_override, self.spotify, self.clock, self.hardware], cfg_override)
        self.assertEqual(mgr2.get_active_plugin().name, "discord_voice")

    def test_spotify_custom_speed_render(self):
        track = {"title": "Test Title with Very Long Scrolling Text", "artist": "Artist"}
        gif_fast = scenes.spotify_scene(track, None, playing=True, options={"text_speed_ms": 40})
        gif_slow = scenes.spotify_scene(track, None, playing=True, options={"text_speed_ms": 120})
        self.assertTrue(gif_fast.startswith(b"GIF89a"))
        self.assertTrue(gif_slow.startswith(b"GIF89a"))
        self.assertGreater(len(gif_fast), 500)

    def test_weather_scene_and_plugin_render(self):
        cfg = {**self.config, "weather_carousel": True}
        weather = WeatherPlugin(cfg)
        weather.weather_data = {
            "city": "Berlin",
            "temp": 4,
            "code": 3,
            "is_day": True,
            "icon": "cloud",
            "condition": "Bedeckt",
            "temp_max": 6,
            "temp_min": 2,
        }
        self.assertTrue(weather.should_display())
        gif_bytes, dur = weather.render()
        self.assertTrue(gif_bytes.startswith(b"GIF89a"))
        self.assertGreater(len(gif_bytes), 300)

    def test_spotify_with_weather_render(self):
        weather = WeatherPlugin(self.config)
        weather.weather_data = {
            "city": "Berlin",
            "temp": 4,
            "icon": "cloud",
            "condition": "Bedeckt",
        }
        spot = SpotifyPlugin(self.config, weather_plugin=weather)
        spot.media_state = ({"title": "Song", "artist": "Artist"}, None, True, (10, 100))
        gif_bytes, dur = spot.render()
        self.assertTrue(gif_bytes.startswith(b"GIF89a"))
        self.assertGreater(len(gif_bytes), 500)

    def test_force_display(self):
        ok = self.mgr.force_display("hardware", duration=10.0)
        self.assertTrue(ok)
        active = self.mgr.get_active_plugin()
        self.assertEqual(active.name, "hardware")

    def test_flip_clock_horizontal_render(self):
        gif = scenes.flip_clock_scene(weather_data={"temp": 5, "icon": "sun"}, options={"flip_style": "horizontal"})
        self.assertTrue(gif.startswith(b"GIF89a"))
        self.assertGreater(len(gif), 300)

    def test_flip_clock_vertical_render(self):
        gif = scenes.flip_clock_scene(options={"flip_style": "vertical"})
        self.assertTrue(gif.startswith(b"GIF89a"))
        self.assertGreater(len(gif), 300)

    def test_paused_spotify_yields_to_flip_clock(self):
        cfg = {"show_paused_spotify": False, "clock_style": "flip"}
        spot = SpotifyPlugin(cfg)
        clock = ClockPlugin(cfg)
        mgr = PriorityManager([spot, clock], cfg)

        # When spotify is playing: spot is active
        spot.media_state = ({"title": "Song", "artist": "Artist"}, None, True, (10, 100))
        self.assertTrue(spot.should_display())
        self.assertEqual(mgr.get_active_plugin().name, "spotify")

        # When spotify is paused: spot should not display, clock becomes active!
        spot.media_state = ({"title": "Song", "artist": "Artist"}, None, False, (10, 100))
        self.assertFalse(spot.should_display())
        self.assertEqual(mgr.get_active_plugin().name, "clock")


    def test_spotify_mini_font_render(self):
        track = {"title": "Birds of a Feather", "artist": "Billie Eilish"}
        gif_normal = scenes.spotify_scene(track, None, playing=True, options={"spotify_font_mini": False})
        gif_mini = scenes.spotify_scene(track, None, playing=True, options={"spotify_font_mini": True})
        self.assertTrue(gif_normal.startswith(b"GIF89a"))
        self.assertTrue(gif_mini.startswith(b"GIF89a"))
        self.assertGreater(len(gif_mini), 500)

    def test_discord_disabled_in_config(self):
        cfg = {"discord_enabled": False}
        disc = DiscordPlugin(cfg)
        disc.send_test_alert("Max", "Hello")
        self.assertFalse(disc.should_display())

    def test_night_time_helper(self):
        from core.lan_control import is_night_time
        self.assertTrue(is_night_time("23:30", "23:00", "07:00"))
        self.assertTrue(is_night_time("03:15", "23:00", "07:00"))
        self.assertFalse(is_night_time("14:00", "23:00", "07:00"))
        self.assertTrue(is_night_time("02:00", "01:00", "05:00"))
        self.assertFalse(is_night_time("06:00", "01:00", "05:00"))

    def test_timer_plugin_and_scene(self):
        from plugins.timer_plugin import TimerPlugin
        tp = TimerPlugin({})
        self.assertFalse(tp.should_display())
        tp.start_timer(25, "FOKUS")
        self.assertTrue(tp.should_display())
        self.assertEqual(tp.priority, 70)
        gif, _ = tp.render()
        self.assertTrue(gif.startswith(b"GIF89a"))
        self.assertGreater(len(gif), 200)
        done_gif = scenes.timer_scene(0, 60, "FOKUS", finished=True)
        self.assertTrue(done_gif.startswith(b"GIF89a"))
        tp.stop_timer()
        self.assertFalse(tp.should_display())

    def test_custom_art_plugin(self):
        from plugins.custom_art_plugin import CustomArtPlugin
        cap = CustomArtPlugin({})
        self.assertFalse(cap.should_display())
        pixels = ["#00e5ff"] * 1024
        self.assertTrue(cap.set_pixels(pixels))
        self.assertTrue(cap.should_display())
        gif, _ = cap.render()
        self.assertTrue(gif.startswith(b"GIF89a"))
        cap.clear()
        self.assertFalse(cap.should_display())

    def test_twitch_plugin_and_scene(self):
        from plugins.twitch_plugin import TwitchPlugin
        tw = TwitchPlugin({"twitch_channels": "Papaplatte, Gronkh"})
        self.assertEqual(tw._get_channels(), ["papaplatte", "gronkh"])
        self.assertFalse(tw.should_display())
        tw.trigger_test_alert("Papaplatte", "Just Chatting")
        self.assertTrue(tw.should_display())
        gif, _ = tw.render()
        self.assertTrue(gif.startswith(b"GIF89a"))
        self.assertGreater(len(gif), 300)

    def test_game_plugin_and_scene(self):
        from plugins.game_plugin import GamePlugin
        gm = GamePlugin({})
        gm.active_game = "WoW"
        gm.accent_color = "#ffb300"
        gm.started_at = 0.0
        self.assertTrue(gm.should_display())
        gif, _ = gm.render()
        self.assertTrue(gif.startswith(b"GIF89a"))
        self.assertGreater(len(gif), 300)

    def test_tray_icon_image(self):
        from core.tray_icon import _build_tray_image
        img = _build_tray_image()
        self.assertEqual(img.size, (64, 64))

    def test_wow_plugin_and_scene(self):
        from plugins.wow_plugin import WoWPlugin, parse_wow_saved_variables
        lua = '''
GoveePixelStatsDB = {
    ["name"] = "Mauro",
    ["class"] = "MAGE",
    ["level"] = 80,
    ["ilvl"] = 638,
    ["crit"] = 31.5,
    ["haste"] = 22.1,
    ["mastery"] = 44.0,
    ["vers"] = 6.2,
    ["gold"] = 145000,
    ["zone"] = "Dornogal",
}
'''
        parsed = parse_wow_saved_variables(lua)
        self.assertEqual(parsed["name"], "Mauro")
        self.assertEqual(parsed["ilvl"], 638)
        self.assertEqual(parsed["crit"], 31.5)

        wp = WoWPlugin({})
        wp.stats = parsed
        wp.wow_is_running = True
        self.assertTrue(wp.should_display())
        gif, _ = wp.render()
        self.assertTrue(gif.startswith(b"GIF89a"))
        self.assertGreater(len(gif), 400)


if __name__ == "__main__":
    unittest.main()
