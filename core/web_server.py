"""Local Web Dashboard and REST API server for Govee Pixel Hub."""
import base64
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from typing import Any, Callable, Dict, Optional


class PixelWebHandler(BaseHTTPRequestHandler):
    hub_manager = None
    web_dir = Path(__file__).parent.parent / "web"

    def _send_json(self, data: Any, code: int = 200) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def _send_bytes(self, data: bytes, content_type: str = "image/png", code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]

        if path in ("/", "/index.html"):
            index_file = self.web_dir / "index.html"
            if index_file.exists():
                self._send_bytes(index_file.read_bytes(), "text/html; charset=utf-8")
            else:
                self.send_error(404, "Index file not found")
            return

        if path == "/api/status":
            if self.hub_manager:
                self._send_json(self.hub_manager.get_full_status())
            else:
                self._send_json({"status": "hub not attached"})
            return

        if path == "/api/live.png":
            if self.hub_manager and self.hub_manager.ble_driver.last_png:
                self._send_bytes(self.hub_manager.ble_driver.last_png, "image/png")
            else:
                # Return empty 1x1 png
                self._send_bytes(
                    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82",
                    "image/png",
                )
            return

        if path == "/api/live.gif":
            if self.hub_manager and self.hub_manager.ble_driver.last_gif:
                self._send_bytes(self.hub_manager.ble_driver.last_gif, "image/gif")
            else:
                self.send_error(404, "No live GIF available yet")
            return

        self.send_error(404)

    def do_POST(self) -> None:
        path = self.path.split("?")[0]
        content_len = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_len) if content_len > 0 else b"{}"

        try:
            body = json.loads(post_data.decode("utf-8")) if post_data else {}
        except Exception:
            body = {}

        if path in ("/api/test_notification", "/api/alert"):
            sender = body.get("sender", "Discord")
            message = body.get("message", "Test Benachrichtigung! 🎮")
            if self.hub_manager:
                self.hub_manager.trigger_test_notification(sender, message)
                self._send_json({"success": True, "sender": sender, "message": message})
            else:
                self._send_json({"success": False, "error": "No hub"}, 500)
            return

        if path == "/api/test_twitch":
            streamer = body.get("streamer", "Papaplatte")
            game = body.get("game", "Just Chatting")
            if self.hub_manager:
                self.hub_manager.twitch.trigger_test_alert(streamer, game)
                self._send_json({"success": True, "streamer": streamer, "game": game})
            else:
                self._send_json({"success": False}, 500)
            return

        if path == "/api/timer":
            if not self.hub_manager:
                self._send_json({"success": False}, 500)
                return
            action = body.get("action", "start")
            if action == "stop":
                self.hub_manager.timer.stop_timer()
                self._send_json({"success": True, "running": False})
            else:
                minutes = float(body.get("minutes", 25))
                label = str(body.get("label", "FOKUS"))
                self.hub_manager.timer.start_timer(minutes=minutes, label=label)
                self._send_json({"success": True, "running": True, "minutes": minutes, "label": label})
            return

        if path == "/api/custom_art":
            if not self.hub_manager:
                self._send_json({"success": False}, 500)
                return
            action = body.get("action", "set")
            duration = float(body.get("duration", 0))
            if action == "clear":
                self.hub_manager.custom_art.clear()
                self._send_json({"success": True, "cleared": True})
            elif "pixels" in body:
                ok = self.hub_manager.custom_art.set_pixels(body["pixels"], duration=duration)
                self._send_json({"success": ok}, 200 if ok else 400)
            elif "image_b64" in body:
                raw_b64 = str(body["image_b64"]).split(",")[-1]
                ok = self.hub_manager.custom_art.set_image_bytes(base64.b64decode(raw_b64), duration=duration)
                self._send_json({"success": ok}, 200 if ok else 400)
            else:
                self._send_json({"success": False}, 400)
            return

        if path == "/api/brightness":
            if not self.hub_manager:
                self._send_json({"success": False}, 500)
                return
            from core.lan_control import DEFAULT_LAN_IP, set_lan_brightness
            val = int(body.get("value", 100))
            ip = self.hub_manager.config.get("lan_ip", DEFAULT_LAN_IP)
            ok = set_lan_brightness(val, ip=ip)
            self._send_json({"success": ok, "value": val})
            return

        if path == "/api/switch_plugin":
            target = body.get("plugin")
            duration = float(body.get("duration", 30.0))
            if self.hub_manager and target:
                ok = self.hub_manager.priority_manager.force_display(target, duration)
                self._send_json({"success": ok, "forced": target})
            else:
                self._send_json({"success": False}, 400)
            return

        if path == "/api/config":
            if self.hub_manager and body:
                self.hub_manager.update_config(body)
                self._send_json({"success": True, "config": self.hub_manager.config})
            else:
                self._send_json({"success": False}, 400)
            return

        self.send_error(404)

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress noisy HTTP request logging
        pass


class PixelWebServer:
    def __init__(self, hub_manager, host: str = "127.0.0.1", port: int = 5000):
        self.hub_manager = hub_manager
        self.host = host
        self.port = port
        self.server: Optional[ThreadingHTTPServer] = None
        self.thread: Optional[threading.Thread] = None

    def start(self) -> None:
        PixelWebHandler.hub_manager = self.hub_manager
        try:
            self.server = ThreadingHTTPServer((self.host, self.port), PixelWebHandler)
        except OSError:
            # Fallback to alternate port if 5000 is taken
            self.port = 5050
            self.server = ThreadingHTTPServer((self.host, self.port), PixelWebHandler)

        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        print(f"Web Dashboard running at http://{self.host}:{self.port}/", flush=True)

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
