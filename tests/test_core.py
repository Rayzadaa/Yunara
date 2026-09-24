"""Unit tests for the bot's pure logic — no browser, no Qt, no network.

Run: `pytest -q`. These cover the parsing/crypto/versioning helpers that used to
be hand-verified before each release, so regressions get caught in CI.
"""
import json
import time

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
    assert not engine._is_lazada_host("https://evillazada.sg/x")      # look-alike, not a subdomain
    assert not engine._is_lazada_host("not a url")


# ─── engine: amount extraction + session path ─────────────────────

def test_extract_amount():
    assert engine._extract_amount("Total $12.50 paid") == "$12.50"
    assert engine._extract_amount("$5.00 and $12.34") == "$12.34"  # picks the max
    assert engine._extract_amount("no amount here") == ""
    # PayNow reserve page shows "SGD 8.29" / "S$8.29" — must be caught too.
    assert engine._extract_amount("Pay within 30 min: SGD 8.29") == "$8.29"
    assert engine._extract_amount("S$12.50 due now") == "$12.50"
    assert engine._extract_amount("bare 8.29 no currency") == ""


def test_session_cookies_filters_non_lazada(tmp_path):
    p = str(tmp_path / "lazada_session.json")
    secure_store.save(p, {"cookies": [
        {"name": "lzd_sid", "value": "SECRET", "domain": ".lazada.sg", "path": "/"},
        {"name": "evil", "value": "NOPE", "domain": ".evil.com", "path": "/"},
        {"name": "lookalike", "value": "NOPE", "domain": ".evillazada.sg", "path": "/"},
        {"name": "lzdcom", "value": "OK", "domain": ".lazada.com", "path": "/"},
    ], "origins": []})
    got = engine.session_cookies(p)
    names = {c["name"] for c in got}
    assert names == {"lzd_sid", "lzdcom"}          # non-Lazada cookie dropped
    assert engine.session_cookies(p) == got         # mtime cache returns the same
    assert engine.session_cookies(str(tmp_path / "missing.json")) == []


def test_http_session_cookies_are_domain_scoped(tmp_path):
    """Session cookies must never be sent to a non-Lazada host (redirect/extracted link)."""
    import requests
    from requests.cookies import get_cookie_header
    s = engine._http_session([
        {"name": "lzd_sid", "value": "SECRET", "domain": ".lazada.sg", "path": "/"}])
    to_evil = get_cookie_header(s.cookies, requests.Request("GET", "https://evil.com/x").prepare())
    to_lzd = get_cookie_header(s.cookies, requests.Request("GET", "https://www.lazada.sg/p.html").prepare())
    assert not to_evil                    # nothing leaks off-domain
    assert "SECRET" in (to_lzd or "")     # but Lazada does get it


def test_http_stock_caches_resolved_short_link(monkeypatch):
    """A short link should be resolved once, then polled directly (1 request, not 2)."""
    short = "https://s.lazada.sg/s.ABC"
    real = "https://www.lazada.sg/products/thing-i123-s456.html"
    calls = []

    class Resp:
        def __init__(self, url, text):
            self.url, self.text, self.ok = url, text, True

    def fake_get(u, **kw):
        calls.append(u)
        if u == short:
            return Resp(short, f'stub <a href="{real}">x</a>')
        return Resp(real, "add to cart")

    monkeypatch.setattr(engine.requests, "get", fake_get)
    engine._RESOLVED.pop(short, None)
    assert engine.http_stock(short) == "in_stock"
    assert calls == [short, real]           # cold: stub + real page
    calls.clear()
    assert engine.http_stock(short) == "in_stock"
    assert calls == [real]                  # warm: straight to the product page
    engine._RESOLVED.pop(short, None)


def test_http_stock_never_follows_a_short_link_off_lazada(monkeypatch):
    """A stub pointing at a look-alike host must not be fetched, trusted or cached."""
    short = "https://s.lazada.sg/s.EVIL"
    lookalike = "https://www.lazada.sg.evil.com/products/thing-i1-s2.html"
    calls = []

    class Resp:
        def __init__(self, url, text):
            self.url, self.text, self.ok = url, text, True

    def fake_get(u, **kw):
        calls.append(u)
        return Resp(u, f'stub <a href="{lookalike}">x</a>' if u == short else "add to cart")

    monkeypatch.setattr(engine.requests, "get", fake_get)
    engine._RESOLVED.pop(short, None)
    assert engine.http_stock(short) == "unknown"
    assert calls == [short] and short not in engine._RESOLVED


def test_http_stock_blames_the_proxy_only_when_one_is_used(monkeypatch):
    import requests

    def unreachable(u, **kw):
        raise requests.exceptions.ProxyError("Unable to connect to proxy")

    monkeypatch.setattr(engine.requests, "get", unreachable)
    url = "https://www.lazada.sg/products/x-i1.html"
    assert engine.http_stock(url, None, "dead.host:8603:user:pass") == "proxy_error"
    assert engine.http_stock(url) == "unknown"                        # direct: just a missed poll
    assert engine.http_stock(url, None, "not-a-proxy") == "proxy_error"  # never silently goes direct


# ─── engine: checkout outcome ─────────────────────────────────────

def test_left_checkout_ignores_query_and_fragment_changes():
    """'PayNow' on the page only counts as an outcome once we've left checkout — the
    checkout page itself lists "PayNow Transfer"."""
    class Page:
        def __init__(self, url):
            self.url = url
    co = "https://checkout.lazada.sg/shipping?spm=a2o42.pdp_revamp.main_page.bottom_bar_main_button"
    assert not engine._left_checkout(Page(co), co, False)
    assert not engine._left_checkout(Page("https://checkout.lazada.sg/shipping?x=1#pay"), co, False)
    assert engine._left_checkout(Page("https://checkout.lazada.sg/payment?orderId=1"), co, False)
    assert engine._left_checkout(Page(co), co, True)                 # a new tab opened
    assert engine._CONFIRM_SELECTION.match("  Confirm Selection ")
    assert not engine._CONFIRM_SELECTION.match("Confirm")             # not a generic confirm


# ─── engine: proxy test messages ──────────────────────────────────

def test_proxy_errors_say_what_actually_went_wrong():
    """A dead gateway used to log 80 chars of urllib3 noise ("HTTPSConnectionPool(host=
    'api.ipify.org'… Max retries exceeded with u") that named the wrong host."""
    dns = ("HTTPSConnectionPool(host='api.ipify.org', port=443): Max retries exceeded (Caused by "
           "ProxyError('Unable to connect to proxy', NameResolutionError(\"Failed to resolve "
           "'gw.example-proxies.com' ([Errno 11001] getaddrinfo failed)\")))")
    assert engine._proxy_error(Exception(dns)) == "host not found (DNS) — check the proxy's gateway hostname"
    assert "407" in engine._proxy_error(Exception("Tunnel connection failed: 407 Proxy Authentication Required"))
    assert "timed out" in engine._proxy_error(Exception("Read timed out. (read timeout=15)"))
    assert "refused" in engine._proxy_error(Exception("[WinError 10061] the target machine actively refused it"))
    assert engine._proxy_error(Exception("something else\nsecond line")) == "something else"


# ─── engine: Lazada verification (slider / baxia dialog) ──────────

class _FakePage:
    url = "https://www.lazada.sg/"

    def __init__(self, present=""):
        self.present = present

    def query_selector(self, sel):
        class El:
            @staticmethod
            def is_visible():
                return True
        return El() if sel == self.present else None


def test_baxia_dialog_counts_as_verification():
    """Lazada's anti-bot dialog is a full-page mask that swallows clicks — it must
    register like the slider does (it silently ate the Login click before v2.9.26)."""
    assert engine.check_for_captcha(_FakePage(".baxia-dialog-mask"))
    assert engine.check_for_captcha(_FakePage(".baxia-dialog"))
    assert engine.check_for_captcha(_FakePage(".nc-container"))
    assert not engine.check_for_captcha(_FakePage(".ordinary-page-element"))


def test_wait_for_verification_waits_for_the_solve_then_continues(monkeypatch):
    states = iter([True, True, False])
    monkeypatch.setattr(engine, "check_for_captcha", lambda page: next(states, False))
    monkeypatch.setattr(engine, "handle_captcha", lambda page, log: False)
    monkeypatch.setattr(engine, "notify", lambda *a, **k: None)
    logs = []
    assert engine.wait_for_verification(_FakePage(), logs.append, timeout=20) is True
    assert any("solve it in the browser window" in m for m in logs), logs
    assert any("cleared" in m for m in logs), logs


def test_wait_for_verification_gives_up_when_never_solved(monkeypatch):
    monkeypatch.setattr(engine, "check_for_captcha", lambda page: True)
    monkeypatch.setattr(engine, "handle_captcha", lambda page, log: False)
    monkeypatch.setattr(engine, "notify", lambda *a, **k: None)
    assert engine.wait_for_verification(_FakePage(), lambda m: None, timeout=0.5) is False
    monkeypatch.setattr(engine, "check_for_captcha", lambda page: False)
    assert engine.wait_for_verification(_FakePage(), lambda m: None) is True   # nothing in the way


# ─── engine: refused orders + one checkout per account ────────────

def test_refused_account_pause_expires_or_lifts_on_fresh_login(tmp_path):
    sess = str(tmp_path / "lazada_session.json")
    open(sess, "w").write("{}")
    engine._ACCOUNT_PAUSE.clear()
    assert engine.checkout_pause("acct") == (0, None)
    assert engine.pause_account_checkouts("acct", sess, seconds=60) is True     # fresh → alert
    assert engine.pause_account_checkouts("acct", sess, seconds=60) is False    # already paused → no 2nd alert
    left, pid = engine.checkout_pause("acct")
    assert 50 < left <= 60 and pid
    assert engine.checkout_pause("other")[0] == 0                              # other accounts unaffected
    t = engine.os.path.getmtime(sess) + 5
    engine.os.utime(sess, (t, t))                                              # a fresh login rewrites it
    assert engine.checkout_pause("acct") == (0, None)
    engine.pause_account_checkouts("acct", sess, seconds=-1)                   # already expired
    assert engine.checkout_pause("acct") == (0, None)


def test_checkout_slot_one_at_a_time_per_account_and_never_while_paused(tmp_path, monkeypatch):
    import threading
    monkeypatch.setattr(engine.notifier, "send_event", lambda *a, **k: True)
    engine._ACCOUNT_PAUSE.clear()
    mk = lambda: engine.TaskWorker({"name": "T", "url": "u"}, lambda *a: None, lambda *a: None)
    a, b, other = mk(), mk(), mk()
    order = []
    with a._checkout_slot("acct", "u") as go_a:
        assert go_a
        with other._checkout_slot("someone-else", "u") as go_o:               # different account: no wait
            assert go_o

        def second():
            with b._checkout_slot("acct", "u") as go_b:
                order.append(("b", bool(go_b)))
        th = threading.Thread(target=second)
        th.start()
        time.sleep(0.6)
        order.append(("a done", True))                                         # b must still be waiting
    th.join(5)
    assert order == [("a done", True), ("b", True)], order

    sess = str(tmp_path / "s.json")
    open(sess, "w").write("{}")
    engine.pause_account_checkouts("acct", sess, seconds=60)
    with a._checkout_slot("acct", "u") as go:
        assert not go
    assert engine._checkout_lock("acct").acquire(blocking=False)               # a paused slot holds no lock
    engine._checkout_lock("acct").release()
    engine._ACCOUNT_PAUSE.clear()


def test_checkout_slot_is_handed_on_as_soon_as_the_order_is_in():
    """Confirming a PayNow outcome takes 8-20s on the real site; a second drop on the
    same account must start as soon as Place Order is clicked, not after that wait."""
    import threading
    mk = lambda: engine.TaskWorker({"name": "T", "url": "u"}, lambda *a: None, lambda *a: None)
    a, b = mk(), mk()
    got_in = threading.Event()
    with a._checkout_slot("acct2", "u") as slot:
        assert slot

        def second():
            with b._checkout_slot("acct2", "u") as s2:
                if s2:
                    got_in.set()
        th = threading.Thread(target=second)
        th.start()
        assert not got_in.wait(0.5)            # still A's turn
        slot.release()                          # A clicked Place Order
        assert got_in.wait(3)                   # B goes straight away, while A is still confirming
        slot.release()                          # releasing twice is harmless
    th.join(5)


# ─── notifier: background delivery ────────────────────────────────

def test_discord_messages_never_hold_up_the_caller_and_stay_in_order(monkeypatch):
    sent = []

    class SlowDiscord:
        def post(self, url, **kw):
            time.sleep(0.4)                     # a real webhook call is ~0.7s from here
            sent.append((kw.get("json") or {}).get("embeds", [{}])[0].get("title"))

            class R:
                ok, status_code, text = True, 204, ""
            return R()

    monkeypatch.setattr(notifier.requests, "Session", SlowDiscord)
    monkeypatch.setattr(notifier, "_sender", None)
    notifier.set_webhook("https://discord.example/api/webhooks/1/x")
    try:
        t0 = time.time()
        for title in ("🟢 In Stock — buying", "🎉 Order Placed!", "🧾 receipt"):
            assert notifier.send_event(title) is True
        assert time.time() - t0 < 0.2, "the checkout thread waited for Discord"
        notifier.flush(5)
        assert sent == ["🟢 In Stock — buying", "🎉 Order Placed!", "🧾 receipt"], sent
    finally:
        notifier.set_webhook("")


def test_discord_test_button_still_gets_the_real_result(monkeypatch):
    class R:
        def __init__(self, ok):
            self.ok, self.status_code, self.text = ok, 204 if ok else 404, ""
    monkeypatch.setattr(notifier.requests, "post", lambda url, **kw: R(False))
    notifier.set_webhook("https://discord.example/api/webhooks/1/x")
    try:
        assert notifier.send_event("✅ test", wait=True) is False   # a bad URL is reported, not assumed sent
    finally:
        notifier.set_webhook("")


# ─── engine: scheduled start ──────────────────────────────────────

def test_parse_start_at():
    assert engine.parse_start_at("13:05") == (13, 5, 0)
    assert engine.parse_start_at("13:05:30") == (13, 5, 30)
    assert engine.parse_start_at(" 09:00:09 ") == (9, 0, 9)
    assert engine.parse_start_at("0:0:0") == (0, 0, 0)
    for bad in ("", "1300", "25:00", "13:60", "13:05:60", "13:05:30:1", "1pm", "13:-5", "13:xx"):
        try:
            engine.parse_start_at(bad)
            raise AssertionError(f"{bad!r} should be rejected")
        except ValueError:
            pass


def test_scheduled_start_waits_for_the_second(monkeypatch):
    """A drop time with seconds must start ON that second, not up to a minute early."""
    import datetime as dt
    target = dt.datetime.now().replace(microsecond=0) + dt.timedelta(seconds=2)
    started = []
    task = {"name": "T", "url": "https://www.lazada.sg/products/x-i1.html",
            "start_at": target.strftime("%H:%M:%S"), "fast_product": True, "interval": 5}
    monkeypatch.setattr(engine, "session_cookies", lambda f: [])
    monkeypatch.setattr(engine, "http_stock", lambda *a, **k: started.append(time.time()) or "out_of_stock")
    w = engine.TaskWorker(task, lambda n, m: None, lambda n, s: None)
    w.start()
    deadline = time.time() + 10
    while time.time() < deadline and not started:
        time.sleep(0.05)
    w.stop()
    w.join(10)
    assert started, "task never started"
    lag = started[0] - target.timestamp()
    assert 0 <= lag < 0.5, f"started {lag:+.2f}s off the scheduled second"


# ─── engine: task worker ──────────────────────────────────────────

def test_task_worker_can_be_joined_after_it_stops():
    """TaskWorker once shadowed Thread._stop with an Event, so join()/is_alive()
    raised TypeError after the thread finished."""
    w = engine.TaskWorker({"name": "T", "url": "https://www.lazada.sg/products/x-i1.html"},
                          lambda *a: None, lambda *a: None)
    w.stop()      # stopped before starting: run() returns without opening a browser
    w.start()
    w.join(10)
    assert not w.is_alive()


def test_fast_product_drops_a_dead_poll_proxy_without_going_blind(monkeypatch):
    """A proxy that can't connect must not blind detection: that cycle polls on the
    real IP instead, and after two misses the proxy is dropped — not blamed on the
    product, and never treated as a drop."""
    dead, good = "dead.host:8603:user:secretpw", "good.host:8603:user:pw"
    calls = []

    def fake_stock(url, cookies=None, proxy=None):
        calls.append(proxy)
        return "proxy_error" if proxy == dead else "out_of_stock"

    monkeypatch.setattr(engine, "http_stock", fake_stock)
    monkeypatch.setattr(engine, "session_cookies", lambda f: [])
    logs, statuses = [], []
    task = {"name": "T", "url": "https://www.lazada.sg/products/x-i1.html", "interval": 0.05,
            "fast_product": True, "proxies": [dead, good]}
    w = engine.TaskWorker(task, lambda n, m: logs.append(m), lambda n, s: statuses.append(s))
    w.start()
    deadline = time.time() + 15
    while time.time() < deadline and statuses.count("out of stock (fast http)") < 8:
        time.sleep(0.05)
    w.stop()
    w.join(10)
    assert statuses.count("out of stock (fast http)") >= 8, (statuses, logs)
    assert calls.count(dead) == 2                          # two misses, then retired
    assert calls.count(None) == 2                          # each miss polled on the real IP
    assert sum("isn't connecting, dropping it" in m for m in logs) == 1, logs
    assert "DROP — verifying" not in statuses
    assert not any("can't read this product" in m or "secretpw" in m for m in logs), logs


def test_mask_proxy_hides_credentials():
    """Proxy user:pass must never reach bot.log / Discord (the log is plaintext)."""
    assert engine.mask_proxy("host.io:8603:someuser:secretpass") == "host.io:8603:***:***"
    assert engine.mask_proxy("http://1.2.3.4:8080:u:p") == "http://1.2.3.4:8080:***:***"
    assert engine.mask_proxy("1.2.3.4:8080") == "1.2.3.4:8080"     # nothing to hide
    assert engine.mask_proxy("") == ""
    for secret in ("someuser", "secretpass"):
        assert secret not in engine.mask_proxy("host.io:8603:someuser:secretpass")


def test_session_path_pairs_account_and_proxy():
    """Each account+proxy pair keeps its own login — the basis of the pair warning."""
    a = engine.session_path("BB", "")
    b = engine.session_path("BB", "1.2.3.4:8080")
    c = engine.session_path("BB", "9.9.9.9:8080")
    d = engine.session_path("ALT", "1.2.3.4:8080")
    assert len({a, b, c, d}) == 4                       # every pair is distinct
    assert engine.session_path("BB", "1.2.3.4:8080") == b  # and deterministic


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
