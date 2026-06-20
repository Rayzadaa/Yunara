"""Local desktop sound alerts for the Lazada bot.

Complements the Discord webhook for when you're at the PC but away from the
chat: a short audio cue fires on the events that need you (in stock, order
placed, CAPTCHA). The Windows toast/notification itself is shown by the GUI's
system-tray icon; this module owns only the audio. Pure stdlib, Windows-only
sound (silently no-ops elsewhere)."""
import sys
import threading

try:
    import winsound  # stdlib, Windows-only
except Exception:
    winsound = None

# Toggled by the GUI's Alerts dialog; gates the audio cue.
enabled = True


def _play(level):
    if not winsound:
        return
    try:
        if level == "order":
            # Celebratory ascending triad for a successful order.
            for freq in (660, 880, 1175):
                winsound.Beep(freq, 160)
        elif level == "stock":
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        elif level in ("captcha", "error"):
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        else:
            winsound.MessageBeep(-1)
    except Exception:
        pass


def play(level):
    """Non-blocking audio cue. level: 'order' | 'stock' | 'captcha' | 'error'."""
    if not enabled or not winsound:
        return
    threading.Thread(target=_play, args=(level,), daemon=True).start()
