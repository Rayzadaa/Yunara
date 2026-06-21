"""Optional CAPTCHA auto-solving via 2captcha.

Best-effort: reCAPTCHA v2 is supported. Lazada's slider (AliCaptcha/Geetest)
is NOT reliably auto-solvable here and falls back to manual solving in the
visible browser window. Requires CAPTCHA_API_KEY in config.py.
"""
import re
import time

import requests

try:
    from config import CAPTCHA_API_KEY
except Exception:
    CAPTCHA_API_KEY = ""


def available():
    return bool(CAPTCHA_API_KEY and "your_" not in CAPTCHA_API_KEY)


def _solve_recaptcha(sitekey, page_url, log):
    try:
        r = requests.post("https://2captcha.com/in.php", data={
            "key": CAPTCHA_API_KEY, "method": "userrecaptcha",
            "googlekey": sitekey, "pageurl": page_url, "json": 1,
        }, timeout=20)
        rid = r.json().get("request")
        if not rid:
            return None
        for _ in range(24):  # up to ~2 min
            time.sleep(5)
            rr = requests.get("https://2captcha.com/res.php", params={
                "key": CAPTCHA_API_KEY, "action": "get", "id": rid, "json": 1,
            }, timeout=20).json()
            if rr.get("status") == 1:
                return rr.get("request")
            if rr.get("request") != "CAPCHA_NOT_READY":
                return None
    except Exception as e:
        log(f"2captcha error: {e}")
    return None


def try_solve(page, log):
    """Attempt to auto-solve a CAPTCHA on the page. Returns True on success."""
    if not available():
        return False
    try:
        frame = page.query_selector("iframe[src*='recaptcha']")
        if frame:
            src = frame.get_attribute("src") or ""
            m = re.search(r"[?&]k=([^&]+)", src)
            if m:
                token = _solve_recaptcha(m.group(1), page.url, log)
                if token:
                    page.evaluate(
                        "(t)=>{document.querySelectorAll('textarea#g-recaptcha-response')"
                        ".forEach(e=>{e.value=t;});}", token)
                    log("reCAPTCHA token injected")
                    return True
    except Exception as e:
        log(f"captcha solve error: {e}")
    log("CAPTCHA type not auto-solvable (likely slider) — solve it in the window")
    return False
