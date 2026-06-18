"""Core monitoring/checkout engine for the Lazada GUI bot (v2.3).

Each task runs in its own thread with its own Playwright browser context
(+ optional proxy). Sessions are keyed per (account, proxy) so multi-account
and proxied checkout both work.
"""
import hashlib
import os
import random
import re
import threading
import time

import requests
from playwright.sync_api import sync_playwright

import notifier
try:
    import captcha_solver
except Exception:
    captcha_solver = None

VERSION = "2.5"
HERE = os.path.dirname(__file__)
SESSION_FILE = os.path.join(HERE, "lazada_session.json")  # default profile
CHROME_CHANNEL = "chrome"

SEL = {
    "login_link": "a[data-spm-click*='locaid=login']",
    "account_trigger": "#myAccountTrigger",
    "phone_tab": ["li[data-role='tab'][data-tab='phone']", "[data-tab='phone']"],
    "phone_input": ["input[type='tel']", "input[name='phone']", "input[placeholder*='phone' i]"],
    "send_otp": [".iweb-button-mask"],
    "otp_cell": ".iweb-passcode-input-cell",
    "buy_cart_btns": ".add-to-cart-buy-now-btn",
    "sku_selector": ".sku-selector-v2",
    "sku_selected_header": ".sku-prop-content-header",
    "qty_plus": "i.next-icon-add",
    "captcha": [".nc-container", "#nc_1_wrapper", ".nc_iconfont", "#nocaptcha",
                ".J_MIDDLEWARE_FRAME_WIDGET", "iframe[src*='captcha']", "iframe[name*='captcha']"],
    "slider_handle": [".nc_iconfont.btn_slide", ".btn_slide", ".nc-lang-cnt .btn_slide"],
    "slider_track": [".nc_scale", ".scale_text"],
    "place_order_text": "Place Order",
    "thank_you": ".thank-you-heading",
    "thank_you_amount": ".thank-you-amount",
    "thank_you_order": ".thank-you-order-number",
}

_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-SG','en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
window.chrome = window.chrome || {runtime: {}};
"""
_BLOCK_TYPES = {"image", "media", "font"}


def notify(text):
    try:
        notifier.send_message(text)
    except Exception:
        pass


# ─── Per-profile session files (multi-account + proxy-IP fix) ──────

def session_path(account="", proxy_raw=""):
    """Default profile -> the original session file (back-compat). Otherwise a
    file keyed by account label + proxy so each account/IP keeps its own login."""
    key = f"{account}|{proxy_raw}".strip("|")
    if not key:
        return SESSION_FILE
    h = hashlib.md5(key.encode()).hexdigest()[:10]
    return os.path.join(HERE, f"lazada_session_{h}.json")


# ─── Proxy ────────────────────────────────────────────────────────

def parse_proxy(raw):
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    scheme = "http"
    if "://" in raw:
        scheme, raw = raw.split("://", 1)
    parts = raw.split(":")
    if len(parts) == 2:
        return {"server": f"{scheme}://{parts[0]}:{parts[1]}"}
    if len(parts) == 4:
        return {"server": f"{scheme}://{parts[0]}:{parts[1]}", "username": parts[2], "password": parts[3]}
    return None


def test_proxy(raw, timeout=15):
    """Lightweight latency test: fetch a tiny IP-echo endpoint through the proxy
    (no browser, no heavy page) and report round-trip ms + the exit IP."""
    proxy = parse_proxy(raw)
    if not proxy:
        return (False, "unparseable")
    server = proxy["server"]
    if "username" in proxy:
        scheme, rest = server.split("://", 1)
        purl = f"{scheme}://{proxy['username']}:{proxy['password']}@{rest}"
    else:
        purl = server
    proxies = {"http": purl, "https": purl}
    try:
        t0 = time.time()
        r = requests.get("https://api.ipify.org?format=json", proxies=proxies, timeout=timeout)
        ms = int((time.time() - t0) * 1000)
        if not r.ok:
            return (False, f"HTTP {r.status_code}")
        ip = ""
        try:
            ip = r.json().get("ip", "")
        except Exception:
            pass
        return (True, f"ok ({ms} ms, exit IP {ip or '?'})")
    except Exception as e:
        return (False, str(e).splitlines()[0][:80])


def human_pause(min_s=0.3, max_s=0.7):
    time.sleep(random.uniform(min_s, max_s))


# ─── CAPTCHA (incl. slider auto-attempt) ──────────────────────────

def check_for_captcha(page):
    try:
        url = (page.url or "").lower()
        if any(t in url for t in ["/punish", "captcha", "sec.lazada"]):
            return True
        for sel in SEL["captcha"]:
            el = page.query_selector(sel)
            if el and el.is_visible():
                return True
    except Exception:
        pass
    return False


def _try_slider(page, log):
    """Best-effort drag of the Lazada slider handle. Often blocked by trajectory
    checks, but worth a shot before falling back to manual."""
    for sel in SEL["slider_handle"]:
        handle = page.query_selector(sel)
        if handle and handle.is_visible():
            try:
                box = handle.bounding_box()
                if not box:
                    continue
                page.mouse.move(box["x"] + 5, box["y"] + box["height"] / 2)
                page.mouse.down()
                steps = random.randint(20, 30)
                for i in range(steps):
                    page.mouse.move(box["x"] + 5 + (i + 1) * 12 + random.uniform(-2, 2),
                                    box["y"] + box["height"] / 2 + random.uniform(-2, 2))
                    time.sleep(random.uniform(0.005, 0.02))
                page.mouse.up()
                log("attempted slider drag")
                time.sleep(2)
                return not check_for_captcha(page)
            except Exception as e:
                log(f"slider drag error: {e}")
    return False


def handle_captcha(page, log):
    """Try slider drag, then external solver. Returns True if cleared."""
    if _try_slider(page, log):
        return True
    if captcha_solver and captcha_solver.available():
        log("attempting CAPTCHA auto-solve…")
        try:
            if captcha_solver.try_solve(page, log):
                return True
        except Exception as e:
            log(f"captcha solver error: {e}")
    return False


def is_logged_in(page):
    try:
        link = page.query_selector(SEL["login_link"])
        if link and link.is_visible():
            return False
        trig = page.query_selector(SEL["account_trigger"])
        if trig:
            return (trig.inner_text() or "").strip() != ""
        return False
    except Exception:
        return False


def _first(page, selectors):
    for s in selectors:
        el = page.query_selector(s)
        if el:
            return el
    return None


# ─── Lightweight stock pre-check (opt-in) ─────────────────────────

def fast_check(context, url, log):
    """Cheap HTML fetch (uses the context's cookies + proxy) to short-circuit
    obvious out-of-stock cases without a full page render. Conservative: only
    returns 'out_of_stock' when confident, else 'unknown' (caller full-checks)."""
    try:
        resp = context.request.get(url, timeout=15000)
        if not resp.ok:
            return "unknown"
        html = resp.text()
        low = html.lower()
        # Strong out-of-stock signals embedded in the PDP data.
        if re.search(r'"(?:quantity|stock)"\s*:\s*0\b', low) or "out of stock" in low or "sold out" in low:
            return "out_of_stock"
        return "unknown"
    except Exception as e:
        log(f"fast-check error: {e}")
        return "unknown"


def select_variant(page, variant, log):
    if not variant:
        return True
    try:
        scope = page.locator(SEL["sku_selector"])
        loc = scope.get_by_text(variant, exact=True).first
        if loc.count() == 0:
            loc = page.get_by_text(variant, exact=True).first
        loc.wait_for(state="visible", timeout=5000)
        handle = loc.element_handle()
        if not handle:
            log(f"variant {variant!r} not found")
            return False
        page.evaluate(
            "(el) => { const w = el.closest('.sku-variable-img-wrap') || el.parentElement || el; w.click(); }",
            handle,
        )
        log(f"selected variant: {variant}")
        human_pause(0.6, 1.0)
        return True
    except Exception as e:
        log(f"could not select variant {variant!r}: {e}")
        return False


def select_payment(page, payment, log):
    if not payment:
        return True
    try:
        loc = page.get_by_text(payment, exact=False).first
        loc.wait_for(state="visible", timeout=6000)
        try:
            loc.click(timeout=4000)
        except Exception:
            h = loc.element_handle()
            if h:
                page.evaluate(
                    "(el) => { const c = el.closest('label, [role=\"radio\"], li, div') || el; c.click(); }", h)
        log(f"selected payment: {payment}")
        human_pause(0.6, 1.2)
        return True
    except Exception as e:
        log(f"could not select payment {payment!r}: {e}")
        return False


def check_stock(page, url, variant, log):
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_selector(SEL["buy_cart_btns"], timeout=8000)
        except Exception:
            pass
        human_pause()
        if variant:
            select_variant(page, variant, log)
        if check_for_captcha(page):
            return ("captcha", None)
        buttons = page.query_selector_all(SEL["buy_cart_btns"])
        add_to_cart_btn = None
        buy_now_btn = None
        for btn in buttons:
            try:
                if not btn.is_visible():
                    continue
                text = btn.inner_text().strip().lower()
                if "add to cart" in text:
                    add_to_cart_btn = btn
                elif "buy now" in text:
                    buy_now_btn = btn
                elif "add to wishlist" in text:
                    return ("out_of_stock", None)
            except Exception:
                continue
        if add_to_cart_btn:
            return ("in_stock", buy_now_btn)
        return ("out_of_stock", None)
    except Exception as e:
        log(f"stock check error: {e}")
        return ("error", None)


def set_quantity(page, quantity, log):
    if quantity <= 1:
        return
    plus = page.query_selector(SEL["qty_plus"])
    if not plus:
        log("+ button not found — buying quantity 1")
        return
    for _ in range(quantity - 1):
        try:
            page.evaluate("(el) => el.click()", plus)
            human_pause(0.2, 0.4)
        except Exception:
            break


def complete_checkout(page, name, url, max_price, payment, dry_run, log):
    try:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        deadline = time.time() + 12
        while time.time() < deadline:
            try:
                probe = page.inner_text("body").lower()
            except Exception:
                probe = ""
            if "place order" in probe or "lazada wallet" in probe:
                break
            time.sleep(0.5)

        if check_for_captcha(page):
            if not handle_captcha(page, log):
                return "retry"

        safe = "".join(c if c.isalnum() else "_" for c in name)[:30]
        try:
            page.screenshot(path=os.path.join(HERE, f"checkout_{safe}.png"))
        except Exception:
            pass
        log(f"checkout page url: {page.url}")
        body = page.inner_text("body").lower()

        if max_price and max_price > 0:
            nums = [float(x.replace(",", "")) for x in re.findall(r"\$?\s*([\d,]+\.\d{2})", body)]
            total = max(nums) if nums else 0
            if total and total > max_price:
                log(f"ABORT: total {total} exceeds max price {max_price}")
                notify(f"⛔ *{name}* aborted — total ${total} over max ${max_price}")
                return "stop"

        if payment:
            select_payment(page, payment, log)

        place = page.get_by_text(SEL["place_order_text"], exact=False).first
        try:
            place.wait_for(state="visible", timeout=5000)
        except Exception:
            btns = []
            for b in page.query_selector_all("button, [role='button']"):
                try:
                    if b.is_visible():
                        t = b.inner_text().strip()
                        if t and len(t) < 50:
                            btns.append(t)
                except Exception:
                    pass
            log("Place Order not found. visible buttons: " + " | ".join(btns[:15]))
            return "retry"

        if dry_run:
            log("DRY RUN — reached Place Order, NOT clicking.")
            notifier.send_event("🧪 Dry run — ready to buy", description=name, url=url, color=0x9B59B6)
            return "stop"

        existing = list(page.context.pages)
        try:
            place.click(timeout=5000)
        except Exception:
            h = place.element_handle()
            if h:
                page.evaluate("(el) => el.click()", h)

        human_pause(3.0, 5.0)

        # The PayNow / cashier page often opens in a NEW TAB — follow it, else the
        # original tab is left blank and we'd capture an empty screenshot.
        target = page
        for _ in range(12):
            extra = [pg for pg in page.context.pages if pg not in existing]
            if extra:
                target = extra[-1]
                try:
                    target.wait_for_load_state("domcontentloaded", timeout=8000)
                except Exception:
                    pass
                log(f"followed new tab: {target.url}")
                break
            time.sleep(0.5)

        # Let the payment page actually render before reading it.
        try:
            target.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        target.wait_for_timeout(2500)

        if check_for_captcha(target):
            handle_captcha(target, log)

        result_png = os.path.join(HERE, f"checkout_{safe}_result.png")
        try:
            target.screenshot(path=result_png, full_page=True)
        except Exception:
            pass
        try:
            post = target.inner_text("body").lower()
        except Exception:
            post = ""
        post_url = (target.url or "").lower()

        # 1) Instant success — Wallet/card paid, thank-you page.
        if target.query_selector(SEL["thank_you"]):
            amount = ""
            el = target.query_selector(SEL["thank_you_amount"])
            if el:
                amount = el.inner_text().strip()
            order_no = ""
            el = target.query_selector(SEL["thank_you_order"])
            if el:
                order_no = el.inner_text().strip()
            log(f"ORDER PLACED #{order_no} SGD {amount}")
            notifier.send_event("🎉 Order Placed!", description=name, color=0x2ECC71, url=url,
                                fields={"Order": order_no or "—", "Amount": f"SGD {amount or '?'}"}, ping=True)
            # Always push the order/QR page so an AFK user still gets the PayNow QR.
            try:
                notifier.send_file(result_png, f"🧾 {name}: order #{order_no or '?'} — if PayNow, pay the QR within ~30 min")
            except Exception:
                pass
            _record_order(name, order_no, amount)
            return "ok"

        # 2) Per-product purchase limit reached (Lazada OC03) — terminal, no retry.
        if "reached the limit" in post or "oc03" in post:
            log("purchase limit reached (OC03) — account already at max for this item")
            notifier.send_event("🚫 Purchase limit reached",
                                description=f"{name}: your account is already at the max quantity for this product.",
                                color=0x95A5A6, url=url)
            return "limit"

        # 3) Still on the checkout page -> order was NOT placed; retry.
        if "select payment method" in post and "place order" in post:
            log("still on checkout after Place Order — not placed")
            return "retry"

        # 3) Order RESERVED but needs manual payment (PayNow / bank transfer, ~30 min).
        pending_signals = ["paynow", "scan to pay", "scan the qr", "complete your payment",
                           "complete the payment", "pay within", "payment reference", "reference no",
                           "awaiting payment", "pending payment", "order has been placed", "transfer to"]
        if any(s in post for s in pending_signals) or "payment" in post_url or "cashier" in post_url:
            amount = _extract_amount(post)
            log(f"ORDER RESERVED — pending PayNow/manual payment (amount {amount})")
            notifier.send_event("⏰ ORDER RESERVED — PAY WITHIN ~30 MIN",
                                description=f"{name}\nComplete the *PayNow / bank transfer* now — the order is held "
                                            "only ~30 minutes, then it's cancelled.",
                                color=0xE67E22, url=url, fields={"Amount": amount or "?"}, ping=True)
            try:
                notifier.send_file(result_png, f"💳 {name}: scan / pay this within ~30 min")
            except Exception:
                pass
            _record_order(name, "pending-payment", amount)
            return "pending"

        # 4) Couldn't confirm — surface the page so the user can check.
        log("clicked Place Order but could not confirm")
        notifier.send_event("⚠️ Check your order", description=f"{name}: clicked Place Order, unconfirmed.",
                            color=0xF1C40F, url=url)
        try:
            notifier.send_file(result_png, f"{name}: post-checkout page — please verify")
        except Exception:
            pass
        return "stop"
    except Exception as e:
        log(f"checkout error: {e}")
        return "retry"


def _extract_amount(text):
    nums = re.findall(r"\$\s*([\d,]+\.\d{2})", text or "")
    if not nums:
        return ""
    return "$" + max(nums, key=lambda x: float(x.replace(",", "")))


def _record_order(name, order_no, amount):
    try:
        with open(os.path.join(HERE, "orders.log"), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{name}\t{order_no}\t{amount}\n")
    except Exception:
        pass


# ─── Context builders ─────────────────────────────────────────────

def _decorate(context):
    try:
        context.add_init_script(_STEALTH_JS)
    except Exception:
        pass
    try:
        context.route("**/*", lambda route: (
            route.abort() if route.request.resource_type in _BLOCK_TYPES else route.continue_()))
    except Exception:
        pass


def _new_context(playwright, proxy_dict, session_file):
    browser = playwright.chromium.launch(
        channel=CHROME_CHANNEL, headless=False,
        args=["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"])
    ctx_args = {
        "viewport": {"width": 1280, "height": 800},
        "user_agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
        "locale": "en-SG", "timezone_id": "Asia/Singapore",
    }
    if proxy_dict:
        ctx_args["proxy"] = proxy_dict
    if session_file and os.path.exists(session_file):
        ctx_args["storage_state"] = session_file
    context = browser.new_context(**ctx_args)
    _decorate(context)
    return browser, context


# ─── Login (per profile) ──────────────────────────────────────────

class LoginManager:
    def __init__(self, phone, get_otp, log, proxy_raw="", session_file=None):
        self.phone = phone
        self.get_otp = get_otp
        self.log = log
        self.proxy = parse_proxy(proxy_raw)
        self.session_file = session_file or SESSION_FILE

    def run(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(
                channel=CHROME_CHANNEL, headless=False,
                args=["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage", "--start-maximized"])
            ctx_args = {"viewport": {"width": 1280, "height": 800},
                        "locale": "en-SG", "timezone_id": "Asia/Singapore"}
            if self.proxy:
                ctx_args["proxy"] = self.proxy
            context = browser.new_context(**ctx_args)
            try:
                context.add_init_script(_STEALTH_JS)
            except Exception:
                pass
            page = context.new_page()
            try:
                self.log("Opening Lazada…")
                page.goto("https://www.lazada.sg/#?", wait_until="domcontentloaded", timeout=30000)
                human_pause(1.5, 2.5)
                if is_logged_in(page):
                    self.log("Already logged in.")
                    context.storage_state(path=self.session_file)
                    return True

                self.log("Clicking Login…")
                btn = page.query_selector(SEL["login_link"])
                if not btn:
                    self.log("Login button not found.")
                    return False
                btn.click(); human_pause(1.5, 2.5)

                self.log("Selecting phone tab…")
                tab = _first(page, SEL["phone_tab"]) or page.get_by_text("Phone Number", exact=False)
                if tab:
                    try:
                        tab.click()
                    except Exception:
                        pass
                human_pause(1, 1.5)

                self.log("Entering phone number…")
                pin = _first(page, SEL["phone_input"])
                if not pin:
                    self.log("Phone input not found.")
                    return False
                pin.click(); human_pause(0.4, 0.8); pin.fill(self.phone); human_pause(1, 1.5)

                self.log("Requesting SMS code…")
                send = _first(page, SEL["send_otp"]) or page.get_by_text("Send code via SMS", exact=False)
                if send:
                    try:
                        send.click()
                    except Exception:
                        pass
                human_pause(2, 3)

                self.log("Waiting for OTP…")
                otp = self.get_otp()
                if not otp:
                    self.log("No OTP received — login aborted.")
                    return False

                cells = page.query_selector_all(SEL["otp_cell"])
                if cells:
                    for i, digit in enumerate(otp):
                        if i >= len(cells):
                            break
                        cells[i].click(); human_pause(0.15, 0.3)
                        page.keyboard.type(digit); human_pause(0.1, 0.25)
                human_pause(3, 4)

                if check_for_captcha(page):
                    handle_captcha(page, self.log)
                    for _ in range(60):
                        if is_logged_in(page):
                            break
                        time.sleep(2)

                page.wait_for_timeout(2500)
                if not is_logged_in(page):
                    self.log("Login FAILED — still logged-out (check OTP / CAPTCHA).")
                    return False

                trig = page.query_selector(SEL["account_trigger"])
                who = trig.inner_text().strip() if trig else "account"
                self.log(f"Logged in as: {who}")
                notifier.send_event("✅ Logged in", description=who, color=0x3498DB)
                context.storage_state(path=self.session_file)
                return True
            except Exception as e:
                self.log(f"login error: {e}")
                return False
            finally:
                try:
                    browser.close()
                except Exception:
                    pass


# ─── Per-product task worker ──────────────────────────────────────

class TaskWorker(threading.Thread):
    def __init__(self, task, on_log, on_status, on_needs_login=None):
        super().__init__(daemon=True)
        self.task = task
        self.on_log = on_log
        self.on_status = on_status
        self.on_needs_login = on_needs_login or (lambda *a: None)
        self._stop = threading.Event()
        self.purchased = False
        self._account = ""
        self._cur_proxy = ""

    def log(self, m):
        self.on_log(self.task["name"], m)

    def status(self, s):
        self.on_status(self.task["name"], s)

    def stop(self):
        self._stop.set()

    def _await_schedule(self):
        start_at = (self.task.get("start_at") or "").strip()
        if not start_at:
            return
        try:
            import datetime as dt
            hh, mm = [int(x) for x in start_at.split(":")]
            now = dt.datetime.now()
            target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if target <= now:
                target += dt.timedelta(days=1)
            self.status(f"scheduled {start_at}")
            while not self._stop.is_set() and dt.datetime.now() < target:
                time.sleep(1)
        except Exception as e:
            self.log(f"bad start time {start_at!r}: {e}")

    def _wait_for_relogin(self, session_file, prev_mtime):
        self.status("session expired — re-login needed")
        self.on_needs_login(self.task["name"], self._account, self._cur_proxy)
        notify(f"🔑 *{self.task['name']}*: session expired — please re-login.")
        waited = 0
        while not self._stop.is_set() and waited < 300:
            try:
                if os.path.exists(session_file) and os.path.getmtime(session_file) > prev_mtime:
                    self.log("session refreshed — resuming")
                    return True
            except Exception:
                pass
            time.sleep(2); waited += 2
        return False

    def run(self):
        name = self.task["name"]
        url = self.task["url"]
        qty = int(self.task.get("quantity", 1) or 1)
        interval = float(self.task.get("interval", 8) or 8)
        variant = (self.task.get("variant") or "").strip()
        account = (self.task.get("account") or "").strip()
        alert_only = bool(self.task.get("alert_only"))
        dry_run = bool(self.task.get("dry_run"))
        max_price = float(self.task.get("max_price") or 0)
        payment = (self.task.get("payment") or "").strip()
        fast = bool(self.task.get("fast"))
        self._account = account

        # Per-task proxy pool — fails over to the next proxy on a worker error.
        proxies_list = self.task.get("proxies")
        if not proxies_list:
            single = self.task.get("proxy", "")
            proxies_list = [single] if single else [""]

        self._await_schedule()
        announced_stock = False
        fails = 0
        errors = 0  # consecutive errors for backoff
        pidx = 0

        while not self._stop.is_set() and not self.purchased:
            current_raw = proxies_list[pidx % len(proxies_list)]
            self._cur_proxy = current_raw
            proxy = parse_proxy(current_raw)
            session_file = session_path(account, current_raw)
            login_verified = False
            if len(proxies_list) > 1:
                self.log(f"using proxy {(pidx % len(proxies_list)) + 1}/{len(proxies_list)}")
            try:
                with sync_playwright() as p:
                    browser, context = _new_context(p, proxy, session_file)
                    page = context.new_page()
                    rebuild = False
                    try:
                        while not self._stop.is_set() and not self.purchased:
                            # Lightweight pre-check (opt-in) — skip full load on clear OOS.
                            if fast:
                                fc = fast_check(context, url, self.log)
                                if fc == "out_of_stock":
                                    errors = 0
                                    self.status("out of stock (fast)")
                                    self._wait(interval); continue

                            self.status("checking")
                            result, buy_btn = check_stock(page, url, variant, self.log)

                            if result == "captcha":
                                self.status("CAPTCHA")
                                if handle_captcha(page, self.log):
                                    continue
                                errors += 1
                                notify(f"⚠️ *CAPTCHA* on *{name}* — solve in window.")
                                self._wait(self._backoff(interval, errors)); continue

                            if result == "error":
                                errors += 1
                                self._wait(self._backoff(interval, errors)); continue
                            errors = 0

                            if result in ("in_stock", "out_of_stock") and not login_verified:
                                if is_logged_in(page):
                                    login_verified = True
                                    self.log("session authenticated ✓")
                                else:
                                    prev = os.path.getmtime(session_file) if os.path.exists(session_file) else 0
                                    rebuild = self._wait_for_relogin(session_file, prev)
                                    break

                            if result == "in_stock":
                                if alert_only:
                                    if not announced_stock:
                                        announced_stock = True
                                        self.status("IN STOCK (alert only)")
                                        notifier.send_event("🟢 In Stock", description=name, url=url,
                                                            color=0x2ECC71, ping=True)
                                    self._wait(interval); continue
                                announced_stock = False
                                self.status("IN STOCK — buying")
                                notifier.send_event("🟢 In Stock — buying", description=name, url=url,
                                                    color=0xF1C40F, fields={"Qty": qty}, ping=True)
                                if not buy_btn:
                                    self.log("Buy Now missing despite stock")
                                    self._wait(interval); continue
                                set_quantity(page, qty, self.log)
                                human_pause(0.5, 1.0)
                                try:
                                    buy_btn.click()
                                except Exception as e:
                                    self.log(f"buy click failed: {e}")
                                    self._wait(interval); continue
                                human_pause(2, 3)

                                self.status("checking out")
                                outcome = complete_checkout(page, name, url, max_price, payment, dry_run, self.log)
                                if outcome in ("ok", "pending"):
                                    self.purchased = True
                                    self.status("purchased ✓" if outcome == "ok"
                                                else "ORDERED — PAY (PayNow, 30 min)")
                                    return
                                elif outcome == "limit":
                                    self.status("limit reached — stopped")
                                    return
                                elif outcome == "stop":
                                    self.status("checkout stopped")
                                    return
                                else:
                                    fails += 1
                                    if fails >= 3:
                                        self.status("checkout failed — stopped")
                                        notify(f"⚠️ *{name}*: checkout failed 3× — stopped.")
                                        return
                                    self.log(f"checkout retry {fails}/3")
                                    self._wait(min(interval, 5)); continue
                            else:
                                announced_stock = False
                                self.status("out of stock")
                                self._wait(interval)
                    finally:
                        try:
                            browser.close()
                        except Exception:
                            pass
                    if not rebuild:
                        break
                    if self._stop.is_set():
                        break
                    # relogin happened — loop again on the SAME proxy.
            except Exception as e:
                errors += 1
                pidx += 1  # fail over to the next proxy in the pool
                wait = self._backoff(interval, errors)
                self.log(f"worker error: {e}; backing off {wait:.0f}s")
                self.status(f"error (retry {errors})")
                if errors == 1 or errors % 5 == 0:
                    notifier.send_event("💥 Task error", description=f"{name}: {e}", color=0xE74C3C)
                self._wait(wait)

    @staticmethod
    def _backoff(interval, errors):
        return min(interval * (2 ** min(errors, 6)), 300)

    def _wait(self, seconds):
        seconds = seconds + random.uniform(0, max(0.0, seconds * 0.25))
        end = time.time() + seconds
        while time.time() < end and not self._stop.is_set():
            time.sleep(0.2)


# ─── Self-test ────────────────────────────────────────────────────

def self_test(url, log):
    log("self-test: launching…")
    report = []
    try:
        with sync_playwright() as p:
            browser, context = _new_context(p, None, SESSION_FILE)
            page = context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2500)
                for label, sel in {"buy/cart buttons": SEL["buy_cart_btns"],
                                   "account trigger": SEL["account_trigger"],
                                   "sku selector": SEL["sku_selector"]}.items():
                    ok = page.query_selector(sel) is not None
                    report.append(f"{'✓' if ok else '✗'} {label} ({sel})")
                report.append(f"logged in: {is_logged_in(page)}")
            finally:
                browser.close()
    except Exception as e:
        report.append(f"self-test error: {e}")
    for line in report:
        log("self-test: " + line)
    return report
