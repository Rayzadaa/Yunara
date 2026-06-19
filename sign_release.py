"""Dev tool: sign the built release and write its sha256 + signature into
version.json. Run AFTER building Lazada-Bot-Share.zip and setting version/notes.

The private key (signing_key.txt) never leaves this machine / the repo.
"""
import hashlib
import json
import os

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

HERE = os.path.dirname(__file__)
ZIP = os.path.join(HERE, "Lazada-Bot-Share.zip")
MANIFEST = os.path.join(HERE, "version.json")
KEY = os.path.join(HERE, "signing_key.txt")

priv = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(open(KEY).read().strip()))

data = open(ZIP, "rb").read()
sha = hashlib.sha256(data).hexdigest()
sig = priv.sign(sha.encode()).hex()

m = json.load(open(MANIFEST, encoding="utf-8"))
m["sha256"] = sha
m["signature"] = sig
json.dump(m, open(MANIFEST, "w", encoding="utf-8"), indent=2)

print("version :", m.get("version"))
print("sha256  :", sha)
print("signed  :", sig[:24] + "…")
print("version.json updated — commit/push it and attach the zip to the release.")
