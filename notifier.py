import json
import os
import re
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


def _post(payload):
    if not _webhook_url:
        return False
    try:
        r = requests.post(_webhook_url, json=payload, timeout=10)
        if not r.ok:
            print(f"Discord webhook error {r.status_code}: {r.text}")
        return r.ok
    except Exception as e:
        print(f"Discord webhook error: {e}")
        return False


def send_message(text):
    """Plain text notification (no-op if nothing configured)."""
    return _post({"content": _to_discord(text)})


def send_event(title, description="", fields=None, color=0x2ECC71, url=None, ping=False):
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
    return _post(payload)


def send_file(path, content=""):
    """Upload an image/file to the webhook (e.g. a PayNow QR screenshot)."""
    if not _webhook_url or not os.path.exists(path):
        return False
    try:
        with open(path, "rb") as fh:
            files = {"file": (os.path.basename(path), fh, "image/png")}
            body = _to_discord(content)[:1800] if content else ""
            payload = {}
            rid = re.sub(r"\D", "", _role_id) if _role_id else ""
            if rid:
                body = f"<@{rid}> <@&{rid}> " + body
                payload["allowed_mentions"] = {"users": [rid], "roles": [rid]}
            if body:
                payload["content"] = body
            data = {"payload_json": json.dumps(payload)} if payload else {}
            r = requests.post(_webhook_url, data=data, files=files, timeout=20)
            if not r.ok:
                print(f"Discord file error {r.status_code}: {r.text}")
            return r.ok
    except Exception as e:
        print(f"Discord file error: {e}")
        return False
