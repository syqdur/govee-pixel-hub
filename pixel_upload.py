"""Upload a 32x32 GIF to an H6630 through the app's HTTPS/MQTT protocol.

Wire format recovered from Govee Home 7.7.21's pact_h6630 module and
6.6.01's PtUrlService/GetIotCmdPtUrlLinkInfo. Uses diy_bridge's DPAPI session.
No firmware changes; no emulator. A successful call requires a device ACK.
"""
import argparse
import base64
import io
import json
import ssl
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from PIL import Image
import paho.mqtt.client as mqtt

from diy_bridge import read_state

DEVICE = "DB:56:99:0F:BE:5E:B8:CC"
HOST = "https://app2.govee.com"


class SessionExpired(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("Refusing to redirect an authenticated Govee request")


def gif_bytes(path):
    raw = Path(path).read_bytes()
    with Image.open(io.BytesIO(raw)) as im:
        if im.size != (32, 32):
            raise ValueError("Image must be exactly 32x32 pixels")
        if im.format == "GIF" and raw.startswith(b"GIF89a"):
            data = raw
        else:
            frames, delays = [], []
            for i in range(getattr(im, "n_frames", 1)):
                im.seek(i)
                frames.append(im.convert("RGB"))
                delays.append(max(20, int(im.info.get("duration", 100))))
            out = io.BytesIO()
            frames[0].save(out, format="GIF", save_all=True,
                           append_images=frames[1:], duration=delays,
                           loop=0, disposal=2)
            data = out.getvalue()
    # Conservative client-side bound, not a claim about the hardware's limit.
    if len(data) > 1_000_000:
        raise ValueError("GIF exceeds this client's 1 MB transfer limit")
    if not data.startswith(b"GIF89a"):
        raise ValueError("Could not create GIF89a")
    return data


def mode_command():
    command = bytearray(20)
    command[:5] = b"\x33\x05\x0a\xfe\x00"
    for b in command[:-1]:
        command[-1] ^= b
    return bytes(command)


def link_command(link, kind, encoded_length):
    url = link.encode("utf-8")
    if not link.startswith("https://") or len(url) > 4096:
        raise ValueError("Unexpected upload link")
    if kind == 1:
        return b"\xfd\x00\x3c\x00" + len(url).to_bytes(2, "little") + url
    return b"\xff" + encoded_length.to_bytes(4, "little") + url


def acknowledgement(message, transaction, device):
    """Return None for unrelated messages; decode the app's ptUrl result byte."""
    if (message.get("device") != device or message.get("cmd") != "ptUrl"
            or message.get("transaction") != transaction):
        return None
    commands = message.get("op", {}).get("command", [])
    if not commands:
        raise RuntimeError("Device replied without a ptUrl operation result")
    first = base64.b64decode(commands[0], validate=True)
    if len(first) < 3 or first[:2] != b"\x33\x05":
        raise RuntimeError("Unexpected device acknowledgement format")
    return first[2]


class PixelClient:
    def __init__(self, device=DEVICE):
        self.device = device
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, path, body=None):
        headers = dict(read_state().get("headers", {}))
        if not headers.get("Authorization"):
            raise SessionExpired("No saved Govee Desktop session; run diy_bridge learn first")
        # clientType 7 returns encrypted IoT credentials; Android's type 0
        # returns the documented fields used by the Android MQTT client.
        headers.update({"clientType": "0", "appVersion": "7.7.21",
                        "Content-Type": "application/json"})
        request = urllib.request.Request(
            HOST + path, headers=headers,
            data=None if body is None else json.dumps(body).encode("utf-8"))
        try:
            with self.opener.open(request, timeout=25) as response:
                data = json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"Govee HTTP {error.code}") from None
        if data.get("status") == 401:
            raise SessionExpired("Govee session expired; renew through Govee Desktop")
        if data.get("status") != 200:
            raise RuntimeError(f"Govee API status {data.get('status')}")
        return data

    def upload(self, path, timeout=25):
        gif = gif_bytes(path)
        listing = self.request("/bff-app/v1/device/list")["data"]["devices"]
        matches = [d for d in listing if d.get("device") == self.device and d.get("sku") == "H6630"]
        if len(matches) != 1:
            raise RuntimeError("Selected H6630 is absent or ambiguous in this account")
        dev = matches[0]
        settings = dev["deviceExt"]["deviceSettings"]
        if isinstance(settings, str):
            settings = json.loads(settings)
        topic = settings["topic"]
        account_topic = self.request("/account/rest/account/v1/iot", {})["accountTopic"]
        account_id = self.request("/bi/rest/v1/user-informations")["data"]["identity"]
        credentials = self.request("/app/v1/account/iot/key")["data"]
        payload = base64.b64encode(b"\x58\x00\x5d" + gif).decode("ascii")
        body = {"sku": "H6630", "device": self.device, "msg": payload,
                "bleSoftVersion": dev["versionSoft"], "bleHardVersion": dev["versionHard"],
                "wifiSoftVersion": settings["wifiSoftVersion"],
                "wifiHardVersion": settings["wifiHardVersion"]}
        link = self.request("/bff-app/v1/msg-channels?msgId=" + str(time.time_ns()), body)["data"]
        values = [base64.b64encode(link_command(link["link"], link["type"], len(payload))).decode(),
                  base64.b64encode(mode_command()).decode()]
        transaction = "v_" + str(time.time_ns() // 1000)
        envelope = {"msg": {"transaction": transaction, "accountTopic": account_topic,
                            "cmd": "ptUrl", "cmdVersion": 0,
                            "data": {"value": values, "write": True}, "type": 1, "origin": 32}}
        return self._publish(credentials, account_id, account_topic, topic,
                             envelope, transaction, timeout, len(gif))

    def _publish(self, credentials, account_id, account_topic, topic, envelope,
                 transaction, timeout, byte_count):
        connected, subscribed, finished = (threading.Event() for _ in range(3))
        outcome = {}
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                             client_id=f"AP/{account_id}/a{uuid.uuid4()}", protocol=mqtt.MQTTv311)

        def on_connect(c, user, flags, reason, props):
            if reason.is_failure:
                outcome["error"] = "MQTT authentication rejected"
            else:
                c.subscribe(account_topic, qos=1)
            connected.set()

        def on_subscribe(c, user, mid, reasons, props):
            if any(r.is_failure for r in reasons):
                outcome["error"] = "MQTT response subscription rejected"
            subscribed.set()

        def on_message(c, user, message):
            try:
                data = json.loads(message.payload)
                code = acknowledgement(data.get("msg", data), transaction, self.device)
                if code is not None:
                    outcome["code"] = code
                    finished.set()
            except (ValueError, KeyError, RuntimeError) as error:
                outcome["error"] = str(error)
                finished.set()

        client.on_connect, client.on_subscribe, client.on_message = on_connect, on_subscribe, on_message
        context = ssl.create_default_context()
        with tempfile.TemporaryDirectory(prefix="govee-mtls-") as directory:
            cert, key = Path(directory) / "client.pem", Path(directory) / "key.pem"
            cert.write_text(credentials["certificatePem"], encoding="ascii")
            key.write_text(credentials["privateKey"], encoding="ascii")
            context.load_cert_chain(str(cert), str(key))
            cert.unlink()
            key.unlink()
        client.tls_set_context(context)
        endpoint = credentials["endpoint"].removeprefix("ssl://")
        if "/" in endpoint or ":" in endpoint:
            raise RuntimeError("Unexpected MQTT endpoint format")
        started = time.monotonic()
        try:
            client.connect(endpoint, 8883, 30)
            client.loop_start()
            if not connected.wait(12) or outcome.get("error"):
                raise RuntimeError(outcome.get("error", "MQTT connection timed out"))
            if not subscribed.wait(6) or outcome.get("error"):
                raise RuntimeError(outcome.get("error", "MQTT subscription timed out"))
            client.publish(topic, json.dumps(envelope), qos=1, retain=False).wait_for_publish(5)
            if not finished.wait(timeout):
                raise RuntimeError("No matching device acknowledgement; display state unknown")
            if outcome.get("error"):
                raise RuntimeError(outcome["error"])
            if outcome.get("code") != 0:
                raise RuntimeError(f"Display rejected GIF: operation result {outcome.get('code')}")
        finally:
            client.disconnect()
            client.loop_stop()
        result = {"ack": "33 05 00", "gif_bytes": byte_count,
                  "seconds": round(time.monotonic() - started, 2)}
        print("Display accepted GIF: " + json.dumps(result), flush=True)
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--device", default=DEVICE)
    args = parser.parse_args()
    try:
        PixelClient(args.device).upload(args.image)
    except Exception as error:
        raise SystemExit(f"Upload failed: {error}")
