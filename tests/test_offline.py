"""Offline-Tests (keine Hardware): Framekodierung, Redaction, Decode, LAN-Fehlertexte, APK-Scan."""
import io
import json
from pathlib import Path
import unittest
import zipfile

from govee_lab import frames
from govee_lab.redact import redact, redact_text


def test_xor_checksum_roundtrip():
    f = frames.make_frame(0x33, 0x01, b"\x01")
    assert len(f) == 20
    assert frames.xor(f[:19]) == f[19]
    d = frames.decode(f, "tx")
    assert d.ok_checksum and d.pro_type == "write" and d.command == "power"
    assert d.fields.get("on") is True


def test_decode_firmware_reply():
    # aa 06 Antwort "1.00.45"
    payload = b"1.00.45".ljust(17, b"\x00")
    f = frames.make_frame(0xAA, 0x06, payload)
    d = frames.decode(f, "rx")
    assert d.fields.get("text") == "1.00.45"


def test_decode_bad_checksum_flagged():
    f = bytearray(frames.make_frame(0xAA, 0x01))
    f[19] ^= 0xFF
    d = frames.decode(bytes(f), "rx")
    assert not d.ok_checksum


def test_redact_api_key_and_token():
    text = 'Govee-API-Key: 12345678-abcd-ef01-2345-6789abcdef01 and "token":"abc.def.ghi"'
    out = redact_text(text)
    assert "12345678-abcd-ef01" not in out
    assert "abc.def.ghi" not in out


def test_redact_keeps_gatt_uuid():
    gatt = "00010203-0405-0607-0809-0a0b0c0d2b11"
    assert gatt in redact_text(f"char {gatt} props")


def test_redact_dict_masks_secret_keys():
    data = {"api_key": "secret123", "device": "AA:BB", "nested": {"password": "p"}}
    out = redact(data)
    assert out["api_key"] == "***"
    assert out["nested"]["password"] == "***"
    assert out["device"] == "AA:BB"


def test_lan_port_conflict_text():
    from govee_lab.lan import _explain

    class E(OSError):
        pass

    e = E()
    e.winerror = 10048
    assert "belegt" in _explain(e).lower()


def test_apk_scan_on_fake_apk(tmp_path: Path):
    from analysis.apk_scan import run_scan

    apk = tmp_path / "fake.apk"
    with zipfile.ZipFile(apk, "w") as z:
        z.writestr("res/values/strings.xml", "<x>auto upgrade 02:00 ota firmware wlan_control graffiti</x>")
        z.writestr("assets/sku_ic.json", json.dumps([{"sku": "H6630", "ic": 1024}]))
    out = run_scan(str(apk), None, None)
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["funde"]["firmware_update"]
    assert report["funde"]["auto_upgrade"]
    assert report["quellen"]["sku_ic"] == {"H6630": 1024}


def test_time_sync_frame_is_valid_write():
    from govee_lab.ble import time_sync_frame

    f = time_sync_frame(9)
    assert len(f) == 20 and f[0] == 0x33 and f[1] == 0x09
    assert frames.xor(f[:19]) == f[19]


def _build_btsnoop(path: Path, frames_tx: list[bytes], handle: int = 0x0011) -> None:
    import struct

    recs = b""
    for i, value in enumerate(frames_tx, 1):
        att = bytes([0x52]) + struct.pack("<H", handle) + value
        l2 = struct.pack("<HH", len(att), 0x0004) + att
        hf = (0x0040 & 0x0FFF) | (0b10 << 12)
        acl = struct.pack("<HH", hf, len(l2)) + l2
        data = bytes([0x02]) + acl
        recs += struct.pack(">IIIIq", len(data), len(data), 0, 0, i * 1000) + data
    path.write_bytes(b"btsnoop\x00" + struct.pack(">II", 1, 1002) + recs)


def _acl_frame(value: bytes, handle: int = 0x0011) -> bytes:
    import struct

    att = bytes([0x52]) + struct.pack("<H", handle) + value
    l2 = struct.pack("<HH", len(att), 0x0004) + att
    hf = (0x0040 & 0x0FFF) | (0b10 << 12)
    return struct.pack("<HH", hf, len(l2)) + l2


def _build_pklg(path: Path, frames_tx: list[bytes]) -> None:
    import struct

    recs = b""
    for i, value in enumerate(frames_tx, 1):
        payload = _acl_frame(value)
        length = 9 + len(payload)
        recs += struct.pack(">IIIB", length, i, 0, 0x02) + payload
    path.write_bytes(recs)


def test_pklg_matches_btsnoop(tmp_path: Path):
    from govee_ble_local.wire import build as b

    from analysis import pklg

    tx = [b.soft_version_query()]
    tx += b.scene_upload_a3(bytes(range(40)), 0x0A)
    tx += b.scene_upload_a4_mtu(bytes(range(50)), 0x0B, mtu=20)
    log = tmp_path / "cap.pklg"
    _build_pklg(log, tx)
    r = pklg.analyze(log)
    assert r["mitschnitt_typ"] == "pklg"
    assert r["govee_frames"] == len(tx)
    kinds = {u["typ"]: u for u in r["upload_bursts"]}
    assert kinds["A3"]["comm_byte"] == 0x0A and kinds["A4"]["comm_byte"] == 0x0B
    assert bytes.fromhex(kinds["A4"]["value_hex"]).startswith(bytes(range(50)))


def test_btsnoop_reassembles_uploads(tmp_path: Path):
    from govee_ble_local.wire import build as b

    from analysis import btsnoop

    log = tmp_path / "cap.btsnoop"
    tx = [b.soft_version_query()]
    tx += b.scene_upload_a3(bytes(range(40)), 0x0A)
    tx += b.scene_upload_a4_mtu(bytes(range(50)), 0x0B, mtu=20)
    _build_btsnoop(log, tx)
    r = btsnoop.analyze(log)
    assert r["govee_frames"] == len(tx)
    assert "soft_version" in r["skalare_frames"][0]["decoded"]
    kinds = {u["typ"]: u for u in r["upload_bursts"]}
    assert kinds["A3"]["comm_byte"] == 0x0A
    assert kinds["A4"]["comm_byte"] == 0x0B
    # echte Nutzdaten stehen am Anfang des value (danach evtl. Null-Padding)
    assert bytes.fromhex(kinds["A3"]["value_hex"]).startswith(bytes(range(40)))
    assert bytes.fromhex(kinds["A4"]["value_hex"]).startswith(bytes(range(50)))


def test_read_catalog_frames_valid():
    from govee_lab.ble import read_catalog

    for _key, (frame, _label) in read_catalog().items():
        assert len(frame) == 20 and frame[0] == 0xAA
        assert frames.xor(frame[:19]) == frame[19]


if __name__ == "__main__":
    unittest.main()
