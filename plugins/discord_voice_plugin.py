"""Discord Voice Channel & Speaking Indicator plugin via local Discord IPC."""
import asyncio
import json
from pathlib import Path
import struct
import time
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from PIL import Image, ImageDraw

from core.plugin_base import PluginBase
import pixel_font
import scenes

CLIENT_ID = "207646673902501888"
TOKEN_FILE = Path(__file__).parent.parent / "discord_token.json"


class DiscordVoicePlugin(PluginBase):
    name = "discord_voice"
    display_name = "Discord Voice & Talk"
    enabled = True

    @property
    def priority(self) -> int:
        if self.config.get("voice_interrupts_music", False):
            return 70
        return 50

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.pipe = None
        self.channel_id: Optional[str] = None
        self.channel_name: str = ""
        self.members: Dict[str, Dict[str, Any]] = {}
        self.speaking_users: Set[str] = set()
        self.last_speaker: Optional[str] = None
        self.reader_task: Optional[asyncio.Task] = None
        self.running: bool = False
        self.is_connected: bool = False

    async def init(self) -> None:
        self.running = True
        self.reader_task = asyncio.create_task(self._ipc_loop())

    async def close(self) -> None:
        self.running = False
        if self.reader_task:
            self.reader_task.cancel()
        if self.pipe:
            try:
                self.pipe.close()
            except Exception:
                pass
            self.pipe = None

    def _get_token(self) -> Optional[str]:
        if TOKEN_FILE.exists():
            try:
                return json.loads(TOKEN_FILE.read_text()).get("access_token")
            except Exception:
                pass
        return None

    def _send_ipc(self, opcode: int, data: Dict[str, Any]) -> None:
        if not self.pipe:
            return
        payload = json.dumps(data).encode("utf-8")
        header = struct.pack("<II", opcode, len(payload))
        self.pipe.write(header + payload)

    async def _ipc_loop(self) -> None:
        while self.running:
            try:
                if not self.enabled:
                    await asyncio.sleep(2.0)
                    continue

                token = self._get_token()
                if not token:
                    await asyncio.sleep(2.0)
                    continue

                pipe_path = r"\\.\pipe\discord-ipc-0"
                self.pipe = await asyncio.to_thread(open, pipe_path, "r+b", 0)

                # 1. Handshake
                self._send_ipc(0, {"v": 1, "client_id": CLIENT_ID})
                hdr = await asyncio.to_thread(self.pipe.read, 8)
                op, length = struct.unpack("<II", hdr)
                await asyncio.to_thread(self.pipe.read, length)

                # 2. Authenticate
                auth_req = {"cmd": "AUTHENTICATE", "args": {"access_token": token}, "nonce": str(uuid.uuid4())}
                self._send_ipc(1, auth_req)
                hdr = await asyncio.to_thread(self.pipe.read, 8)
                op, length = struct.unpack("<II", hdr)
                auth_resp = json.loads((await asyncio.to_thread(self.pipe.read, length)).decode("utf-8"))

                if auth_resp.get("evt") == "ERROR":
                    print(f"Discord Voice token error: {auth_resp}", flush=True)
                    self.pipe.close()
                    self.pipe = None
                    await asyncio.sleep(5.0)
                    continue

                self.is_connected = True
                print("Discord Voice connected to Discord Client IPC", flush=True)

                # 3. Subscribe to channel events
                self._send_ipc(1, {"cmd": "SUBSCRIBE", "evt": "VOICE_CHANNEL_SELECT", "nonce": str(uuid.uuid4())})

                # 4. Query current channel
                self._send_ipc(1, {"cmd": "GET_SELECTED_VOICE_CHANNEL", "nonce": str(uuid.uuid4())})

                while self.running:
                    hdr = await asyncio.to_thread(self.pipe.read, 8)
                    if not hdr or len(hdr) < 8:
                        break
                    op, length = struct.unpack("<II", hdr)
                    body_bytes = await asyncio.to_thread(self.pipe.read, length)
                    msg = json.loads(body_bytes.decode("utf-8"))
                    self._handle_discord_event(msg)

            except Exception as err:
                self.is_connected = False
                self.channel_id = None
                self.members.clear()
                self.speaking_users.clear()
                if self.pipe:
                    try:
                        self.pipe.close()
                    except Exception:
                        pass
                    self.pipe = None
                await asyncio.sleep(3.0)

    def _handle_discord_event(self, msg: Dict[str, Any]) -> None:
        cmd = msg.get("cmd")
        evt = msg.get("evt")
        data = msg.get("data") or {}

        if cmd == "GET_SELECTED_VOICE_CHANNEL":
            if data and "id" in data:
                self._set_channel(data)
            else:
                self.channel_id = None
                self.members.clear()
                self.speaking_users.clear()
            return

        if evt == "VOICE_CHANNEL_SELECT":
            cid = data.get("channel_id")
            if cid:
                self._send_ipc(1, {"cmd": "GET_SELECTED_VOICE_CHANNEL", "nonce": str(uuid.uuid4())})
            else:
                self.channel_id = None
                self.members.clear()
                self.speaking_users.clear()
            return

        if evt == "SPEAKING_START":
            uid = data.get("user_id")
            if uid:
                self.speaking_users.add(str(uid))
                self.last_speaker = str(uid)
            return

        if evt == "SPEAKING_STOP":
            uid = data.get("user_id")
            if uid and str(uid) in self.speaking_users:
                self.speaking_users.remove(str(uid))
            return

        if evt in ("VOICE_STATE_CREATE", "VOICE_STATE_UPDATE", "VOICE_STATE_DELETE"):
            self._send_ipc(1, {"cmd": "GET_SELECTED_VOICE_CHANNEL", "nonce": str(uuid.uuid4())})

    def _clean_name(self, nick: str) -> str:
        # If user has "Tag | Name" or "Name | Tag", prefer clean name
        parts = [p.strip() for p in nick.replace("・", " ").split("|") if p.strip()]
        if len(parts) > 1:
            # Pick the part that looks more like a human name or Mauro
            chosen = next((p for p in parts if p.lower() in ("mauro", "syq")), parts[-1])
        else:
            chosen = parts[0] if parts else nick
        return chosen[:6]

    def _set_channel(self, data: Dict[str, Any]) -> None:
        self.channel_id = data.get("id")
        raw_name = data.get("name", "Voice")
        clean_name = raw_name.replace("🔊", "").replace("・", "").replace("-", " ").strip()
        self.channel_name = clean_name or "Voice"

        new_members = {}
        for vs in data.get("voice_states", []):
            u = vs.get("user") or {}
            uid = str(u.get("id"))
            nick = vs.get("nick") or u.get("global_name") or u.get("username") or "User"
            v_state = vs.get("voice_state") or {}
            muted = vs.get("mute", False) or v_state.get("self_mute", False) or v_state.get("mute", False)
            new_members[uid] = {
                "id": uid,
                "name": self._clean_name(nick),
                "muted": muted,
            }
        self.members = new_members

        if self.channel_id:
            self._send_ipc(
                1, {"cmd": "SUBSCRIBE", "evt": "SPEAKING_START", "args": {"channel_id": self.channel_id}, "nonce": str(uuid.uuid4())}
            )
            self._send_ipc(
                1, {"cmd": "SUBSCRIBE", "evt": "SPEAKING_STOP", "args": {"channel_id": self.channel_id}, "nonce": str(uuid.uuid4())}
            )

    def should_display(self) -> bool:
        if not self.enabled or not self.channel_id:
            return False
        mode = self.config.get("voice_mode", "always")
        if mode == "off":
            return False
        if mode == "on_speaking":
            return len(self.speaking_users) > 0
        return True

    def get_state_key(self) -> Any:
        if not self.channel_id:
            return None
        members_tuple = tuple(
            sorted((m["id"], m["muted"], m["id"] in self.speaking_users) for m in self.members.values())
        )
        return (self.name, self.channel_id, frozenset(self.speaking_users), members_tuple)

    def render(self) -> Tuple[bytes, float]:
        image = Image.new("RGB", (32, 32), "#0c0d10")
        draw = ImageDraw.Draw(image)

        # 1. Blurple Header (rows 0..6)
        draw.rectangle((0, 0, 31, 6), fill="#5865F2")

        # Mini controller icon at (1, 1)
        icon = ["..#.#..", ".#####.", "##.#.##", ".#####.", "..#.#.."]
        for py, row in enumerate(icon):
            for px, c in enumerate(row):
                if c == "#":
                    draw.point((1 + px, 1 + py), fill="white")

        # Channel name text (rows 0..5)
        display_name = self.channel_name.split()[0] if self.channel_name else "Voice"
        pixel_font.draw_text(image, (10, 0), display_name[:5], fill="white", font_type="normal")

        # Member count on right
        cnt_str = f"[{len(self.members)}]"
        w_cnt = pixel_font.measure_text(cnt_str, "mini")
        pixel_font.draw_text(image, (31 - w_cnt, 1), cnt_str, fill="#c9cdfb", font_type="mini")

        # Dark divider
        draw.line((0, 7, 31, 7), fill="#1e2026")

        # Sort members: speaking first, then last speaker, then unmuted, then muted
        def member_sort(m):
            is_speaking = m["id"] in self.speaking_users
            was_last = m["id"] == self.last_speaker
            is_muted = m.get("muted", False)
            return (0 if is_speaking else (1 if was_last else (2 if not is_muted else 3)), m["name"])

        sorted_members = sorted(self.members.values(), key=member_sort)
        count = len(sorted_members)

        # Dynamic vertical spacing based on member count
        if count == 1:
            y_starts = [15]
        elif count == 2:
            y_starts = [11, 21]
        else:
            y_starts = [9, 17, 25]

        for idx, m in enumerate(sorted_members[:3]):
            y = y_starts[idx]
            is_speaking = m["id"] in self.speaking_users
            is_muted = m.get("muted", False)

            # 5x5 Avatar box on left (x=1..5, y..y+4)
            if is_speaking:
                # Glowing neon green border with bright center
                draw.rectangle((1, y, 5, y + 4), fill="#00e676")
                draw.point((3, y + 2), fill="#ffffff")
            elif is_muted:
                # Dark slate box with red mute cross
                draw.rectangle((1, y, 5, y + 4), fill="#22242a")
                draw.line((2, y + 1, 4, y + 3), fill="#ff5252")
                draw.line((4, y + 1, 2, y + 3), fill="#ff5252")
            else:
                # Subtle idle avatar box
                draw.rectangle((1, y, 5, y + 4), fill="#181a20", outline="#353942")

            # Member name (x=8..31) in crisp FONT_NORMAL
            name_color = "#ffffff" if is_speaking else ("#5a5e6a" if is_muted else "#d0d4dc")
            pixel_font.draw_text(image, (8, y - 1), m["name"][:6], fill=name_color, font_type="normal")

        gif_bytes = scenes._encode([image], [1000])
        return gif_bytes, 2.0

    def get_status_info(self) -> Dict[str, Any]:
        info = super().get_status_info()
        info.update({
            "in_voice": bool(self.channel_id),
            "channel_name": self.channel_name,
            "member_count": len(self.members),
            "speaking": [m["name"] for m in self.members.values() if m["id"] in self.speaking_users],
            "members": [m["name"] for m in self.members.values()],
        })
        return info
