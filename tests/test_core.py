"""Unit tests for the bot's pure logic — no browser, no Qt, no network.

Run: `pytest -q`. These cover the parsing/crypto/versioning helpers that used to
be hand-verified before each release, so regressions get caught in CI.
"""
import json

import engine
import notifier
import secure_store
import updater


# ─── engine: proxy parsing ────────────────────────────────────────

def test_parse_proxy():
    assert engine.parse_proxy("") is None
    assert engine.parse_proxy("garbage") is None
    assert engine.parse_proxy("1.2.3.4:8080") == {"server": "http://1.2.3.4:8080"}
    assert engine.parse_proxy("1.2.3.4:8080:user:pass") == {
        "server": "http://1.2.3.4:8080", "username": "user", "password": "pass"}
    assert engine.parse_proxy("socks5://1.2.3.4:1080") == {"server": "socks5://1.2.3.4:1080"}


# ─── engine: stock parsing ────────────────────────────────────────

def test_parse_stock():
    assert engine._parse_stock('"stock":0') == "out_of_stock"
    assert engine._parse_stock('"quantity":"5"') == "in_stock"
    assert engine._parse_stock("this item is out of stock") == "out_of_stock"
    assert engine._parse_stock("add to cart") == "in_stock"
    assert engine._parse_stock("nothing relevant here") == "unknown"


# ─── engine: host guard (SSRF protection for the logged-in context) ──

def test_is_lazada_host():
    assert engine._is_lazada_host("https://www.lazada.sg/products/x.html")
    assert engine._is_lazada_host("https://s.lazada.sg/s.abc")
    assert engine._is_lazada_host("https://pages.lazada.com/x")
    assert not engine._is_lazada_host("https://evil.com")
    assert not engine._is_lazada_host("https://lazada.sg.evil.com/x")
    assert not engine._is_lazada_host("not a url")


# ─── engine: amount extraction + session path ─────────────────────

def test_extract_amount():
    assert engine._extract_amount("Total $12.50 paid") == "$12.50"
    assert engine._extract_amount("$5.00 and $12.34") == "$12.34"  # picks the max
    assert engine._extract_amount("no amount here") == ""


def test_session_path():
    assert engine.session_path("", "") == engine.SESSION_FILE
    keyed = engine.session_path("main", "")
    assert keyed != engine.SESSION_FILE and keyed.endswith(".json")
    assert engine.session_path("main", "") == engine.session_path("main", "")  # deterministic
    assert engine.session_path("main", "") != engine.session_path("alt", "")


# ─── secure_store: encryption round-trip + recovery ───────────────

def test_secure_store_roundtrip(tmp_path):
    p = str(tmp_path / "s.json")
    state = {"cookies": [{"name": "x", "value": "secret"}], "origins": []}
    secure_store.save(p, state)
    assert secure_store.load(p) == state


def test_secure_store_legacy_plaintext(tmp_path):
    p = str(tmp_path / "legacy.json")
    state = {"cookies": [], "origins": []}
    open(p, "w").write(json.dumps(state))
    assert secure_store.load(p) == state


def test_secure_store_missing_and_corrupt(tmp_path):
    assert secure_store.load(str(tmp_path / "nope.json")) is None
    bad = str(tmp_path / "bad.json")
    open(bad, "wb").write(b"\x00\x01garbage")
    assert secure_store.load(bad) is None


def test_secure_store_foreign_seal_ignored(tmp_path):
    # A dpapi blob sealed elsewhere must not decrypt here (Windows) / on Linux.
    p = str(tmp_path / "foreign.json")
    open(p, "w").write(json.dumps({"v": 1, "enc": "dpapi", "data": "bm90LXJlYWw="}))
    assert secure_store.load(p) is None


# ─── updater: signature verification (fail-closed) ────────────────

def test_verify_signature_roundtrip(monkeypatch):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    priv = Ed25519PrivateKey.generate()
    monkeypatch.setattr(updater, "PUBLIC_KEY_HEX", priv.public_key().public_bytes_raw().hex())
    sha = "a" * 64
    sig = priv.sign(sha.encode()).hex()
    log = lambda *_: None
    assert updater._verify_signature(sha, sig, log) is True
    assert updater._verify_signature(sha, "00" * 64, log) is False   # bad signature
    assert updater._verify_signature(sha, "", log) is False           # missing → fail closed
    assert updater._verify_signature("b" * 64, sig, log) is False     # signed a different hash


def test_ver_compare():
    assert updater._ver("2.9.10") > updater._ver("2.9.9")
    assert updater._ver("2.10.0") > updater._ver("2.9.99")
    assert updater._ver("3.0.0") > updater._ver("2.9.12")
    assert updater._ver("2.9.1") == updater._ver("2.9.1")


def test_update_whitelist_has_shipped_modules():
    for mod in ("engine.py", "gui_app.py", "secure_store.py", "desktop_alert.py", "updater.py"):
        assert mod in updater.UPDATE_FILES


# ─── notifier: markup conversion ──────────────────────────────────

def test_to_discord_bold():
    assert notifier._to_discord("*bold*") == "**bold**"
    assert notifier._to_discord("no markup") == "no markup"
