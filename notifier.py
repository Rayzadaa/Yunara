import atexit
import json
import os
import queue
import re
import threading
import time

import requests

# Notifications go through a Discord webhook only (no bot token needed).
_webhook_url = ""
_role_id = ""


def set_webhook(url):
    global _webhook_url
    _webhook_url = (url or "").strip()


def get_webhook():
    return _webhook_url


def set_role(role_id):
    global _role_id
    _role_id = (role_id or "").strip()


def get_role():
    return _role_id


def _to_discord(text):
    """Convert Telegram-style *bold* markup to Discord **bold**."""
    return re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"**\1**", text)


# ─── Background delivery ──────────────────────────────────────────
# A webhook call costs ~0.7s (new TLS connection each time; up to the 10s timeout
# when Discord is slow), and "In Stock — buying" is sent right before Buy Now — so
# it used to delay every checkout. Messages now go through one FIFO sender thread:
# the caller never waits, they still arrive in order, and one reused connection
# makes delivery itself ~2x faster.

_outbox = queue.Queue()
_sender = None
_sender_lock = threading.Lock()


def _drain():
    http = requests.Session()
    while True:
        job = _outbox.get()
        try:
            job(http)
        except Exception as e:
            print(f"Discord webhook error: {e}")
        finally:
            _outbox.task_done()


def _enqueue(job):
    global _sender
    with _sender_lock:
        if _sender is None or not _sender.is_alive():
            _sender = threading.Thread(target=_drain, name="discord-sender", daemon=True)
            _sender.start()
    _outbox.put(job)


def flush(timeout=5.0):
    """Wait (bounded) for queued notifications to go out — runs at exit, so an order
    alert isn't lost when the app is closed right after a buy."""
    end = time.time() + timeout
    while _outbox.unfinished_tasks and time.time() < end:
        time.sleep(0.05)


atexit.register(flush)


def _send(http, url, retry=True, **kw):
    r = http.post(url, **kw)
    if r.status_code == 429 and retry:  # rate-limited: off the checkout path, so just wait it out
        try:
            wait = float(r.json().get("retry_after", 1))
        except Exception:
            wait = 1.0
        time.sleep(min(max(wait, 0.2), 5))
        return _send(http, url, retry=False, **kw)
    if not r.ok:
        print(f"Discord webhook error {r.status_code}: {r.text}")
    return r.ok


def _dispatch(url, wait, **kw):
    """Send now and return the result (`wait=True`, e.g. the Test button), or queue it
    and return True at once. The URL is captured now, so a settings change can't
    redirect an alert that's already queued."""
    if wait:
        try:
            return _send(requests, url, **kw)
        except Exception as e:
            print(f"Discord webhook error: {e}")
            return False
    _enqueue(lambda http: _send(http, url, **kw))
    return True


def _post(payload, wait=False):
    if not _webhook_url:
        return False
    return _dispatch(_webhook_url, wait, json=payload, timeout=10)


def send_message(text, wait=False):
    """Plain text notification (no-op if nothing configured)."""
    return _post({"content": _to_discord(text)}, wait)


def send_event(title, description="", fields=None, color=0x2ECC71, url=None, ping=False, wait=False):
    """Rich embed notification with optional product link and role @ping."""
    embed = {"title": title, "color": color}
    if description:
        embed["description"] = _to_discord(description)
    if url:
        embed["url"] = url
    if fields:
        embed["fields"] = [{"name": k, "value": str(v), "inline": True} for k, v in fields.items()]
    payload = {"embeds": [embed]}
    if ping and _role_id:
        rid = re.sub(r"\D", "", _role_id)
        if rid:
            # Ping whether the ID is a USER or a ROLE — include both mention forms.
            payload["content"] = f"<@{rid}> <@&{rid}>"
            payload["allowed_mentions"] = {"users": [rid], "roles": [rid]}
    return _post(payload, wait)


def send_file(path, content="", wait=False):
    """Upload an image/file to the webhook (e.g. a PayNow QR screenshot)."""
    if not _webhook_url or not os.path.exists(path):
        return False
    try:
        with open(path, "rb") as fh:
            blob = fh.read()  # read now: the next checkout may overwrite this screenshot
    except Exception as e:
        print(f"Discord file error: {e}")
        return False
    body = _to_discord(content)[:1800] if content else ""
    payload = {}
    rid = re.sub(r"\D", "", _role_id) if _role_id else ""
    if rid:
        body = f"<@{rid}> <@&{rid}> " + body
        payload["allowed_mentions"] = {"users": [rid], "roles": [rid]}
    if body:
        payload["content"] = body
    data = {"payload_json": json.dumps(payload)} if payload else {}
    files = {"file": (os.path.basename(path), blob, "image/png")}
    return _dispatch(_webhook_url, wait, data=data, files=files, timeout=20)
