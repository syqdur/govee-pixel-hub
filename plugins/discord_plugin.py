"""Discord & Windows Toast Notification plugin."""
import time
from typing import Any, Dict, List, Optional, Tuple

from core.plugin_base import PluginBase
import scenes


class DiscordPlugin(PluginBase):
    name = "discord"
    display_name = "Discord & Alerts"
    priority = 100
    enabled = True

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.listener = None
        self.seen_ids = None
        self.queue: List[Tuple[str, str]] = []  # (sender, message)
        self.unread_count: int = 0
        self.current_alert: Optional[Tuple[str, str]] = None
        self.alert_until: float = 0.0

    async def init(self) -> None:
        try:
            from winrt.windows.ui.notifications.management import UserNotificationListener

            self.listener = UserNotificationListener.current
            status = await self.listener.request_access_async()
            if int(status) != 1:
                print("Windows notification access not granted", flush=True)
        except Exception as err:
            print(f"Notification listener init: {err}", flush=True)

    async def poll(self) -> None:
        if not self.listener or not self.enabled or not self.config.get("discord_enabled", True):
            self.unread_count = 0
            self.queue.clear()
            self.current_alert = None
            return
        try:
            from winrt.windows.ui.notifications import KnownNotificationBindings, NotificationKinds

            items = list(await self.listener.get_notifications_async(NotificationKinds.TOAST))
            apps = self.config.get("notify_apps", ["Discord"])

            unread = 0
            first = self.seen_ids is None
            for n in items:
                app_name = ""
                for get_fn in (
                    lambda: n.app_info.display_info.display_name,
                    lambda: n.app_info.app_user_model_id,
                ):
                    try:
                        app_name = get_fn()
                        if app_name:
                            break
                    except OSError:
                        pass

                matched = any(a.lower() in app_name.lower() for a in apps)
                if not matched:
                    continue

                unread += 1
                if first or n.id in self.seen_ids:
                    continue

                # Extract texts
                binding = n.notification.visual.get_binding(KnownNotificationBindings.toast_generic)
                texts = [t.text for t in binding.get_text_elements()] if binding else []
                sender = texts[0] if texts else "Discord"
                body = " ".join(texts[1:]) if len(texts) > 1 else "neue Nachricht"
                self.queue.append((sender, body))
                # Keep queue reasonable
                if len(self.queue) > 5:
                    self.queue = self.queue[-5:]

            self.seen_ids = {n.id for n in items}
            self.unread_count = unread
        except Exception as err:
            print(f"Notification poll error: {err}", flush=True)

    def send_test_alert(self, sender: str = "Discord", message: str = "Test-Nachricht! 👋") -> None:
        """Injects a test notification into the queue."""
        self.queue.append((sender, message))
        self.unread_count = max(1, self.unread_count)

    def should_display(self) -> bool:
        if not self.enabled or not self.config.get("discord_enabled", True):
            return False
        # Active if an alert is currently showing or if items are waiting in the queue
        now = time.monotonic()
        if self.current_alert and now < self.alert_until:
            return True
        return len(self.queue) > 0

    def get_state_key(self) -> Any:
        if self.current_alert and time.monotonic() < self.alert_until:
            return (self.name, self.current_alert[0], self.current_alert[1])
        if self.queue:
            return (self.name, "pending", len(self.queue), self.queue[0])
        return (self.name, "idle", self.unread_count)

    def render(self) -> Tuple[bytes, float]:
        now = time.monotonic()
        # If no current alert or alert expired, pop next
        if not self.current_alert or now >= self.alert_until:
            if self.queue:
                self.current_alert = self.queue.pop(0)
            else:
                self.current_alert = ("Discord", "neue Nachricht")

        sender, message = self.current_alert
        min_sec = self.config.get("notify_min_seconds", 10)

        gif_bytes, loop_dur = scenes.discord_scene(
            sender[:80], (message or "neue Nachricht")[:200], options=self.config
        )
        self.alert_until = now + max(min_sec, loop_dur + 1.0)
        return gif_bytes, max(min_sec, loop_dur + 1.0)

    def get_status_info(self) -> Dict[str, Any]:
        info = super().get_status_info()
        info.update({
            "unread_count": self.unread_count,
            "queued_alerts": len(self.queue),
            "current_alert": self.current_alert if (self.current_alert and time.monotonic() < self.alert_until) else None,
        })
        return info
