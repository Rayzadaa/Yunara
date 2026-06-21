"""At-rest encryption for the per-profile Lazada session files (login cookies).

A session file is full account access (the cookies = a logged-in session), so we
don't want it sitting in plaintext on disk where a backup, cloud-sync folder, or
a copied file would expose the account. On Windows the blob is sealed with DPAPI
(CryptProtectData) bound to the **current Windows user** — another account or
another PC cannot decrypt it, with no password to manage.

Falls back to plaintext if DPAPI is unavailable (non-Windows, or the API fails)
so logins never break. Old plaintext session files load transparently and get
re-sealed on the next save.

On-disk format when encrypted:  {"v":1,"enc":"dpapi","data":"<base64>"}
Otherwise it's a normal Playwright storage_state object (the legacy format).
"""
import base64
import ctypes
import json
import os
import sys
from ctypes import wintypes

_WIN = sys.platform.startswith("win")

if _WIN:
    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_byte))]

    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32
    _BLOBP = ctypes.POINTER(_DATA_BLOB)
    _crypt32.CryptProtectData.argtypes = [
        _BLOBP, wintypes.LPCWSTR, _BLOBP, ctypes.c_void_p, ctypes.c_void_p,
        wintypes.DWORD, _BLOBP]
    _crypt32.CryptProtectData.restype = wintypes.BOOL
    _crypt32.CryptUnprotectData.argtypes = [
        _BLOBP, ctypes.c_void_p, _BLOBP, ctypes.c_void_p, ctypes.c_void_p,
        wintypes.DWORD, _BLOBP]
    _crypt32.CryptUnprotectData.restype = wintypes.BOOL
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p


def _run_dpapi(func, data, descr):
    buf = ctypes.create_string_buffer(bytes(data), len(data))
    blob_in = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    blob_out = _DATA_BLOB()
    if not func(ctypes.byref(blob_in), descr, None, None, None, 0, ctypes.byref(blob_out)):
        return None
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        _kernel32.LocalFree(blob_out.pbData)


def _encrypt(raw):
    if not _WIN:
        return None
    try:
        return _run_dpapi(_crypt32.CryptProtectData, raw, "lazada-session")
    except Exception:
        return None


def _decrypt(blob):
    if not _WIN:
        return None
    try:
        return _run_dpapi(_crypt32.CryptUnprotectData, blob, None)
    except Exception:
        return None


def save(path, state):
    """Write a Playwright storage_state dict to `path`, DPAPI-sealed when possible.
    Atomic (temp file + replace) so a crash mid-write can't corrupt the session."""
    raw = json.dumps(state).encode("utf-8")
    enc = _encrypt(raw)
    if enc is not None:
        blob = json.dumps({"v": 1, "enc": "dpapi",
                           "data": base64.b64encode(enc).decode("ascii")}).encode("utf-8")
    else:
        blob = raw  # plaintext fallback — never block login over encryption
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(blob)
    os.replace(tmp, path)


def load(path):
    """Return the Playwright storage_state dict, or None if absent/unreadable.
    Handles both the sealed format and legacy plaintext files."""
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            obj = json.loads(f.read().decode("utf-8"))
    except Exception:
        return None
    if isinstance(obj, dict) and obj.get("enc") == "dpapi":
        try:
            dec = _decrypt(base64.b64decode(obj["data"]))
            return json.loads(dec.decode("utf-8")) if dec is not None else None
        except Exception:
            return None
    return obj  # legacy plaintext storage_state
