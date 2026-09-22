#!/usr/bin/env python3
"""defects.json → defects.signed.json. Das CLI um `envelope.wrap()`.

Der private Schlüssel kommt aus einer Umgebungsvariablen (`--key-env`), nicht
aus einer Datei im Arbeitsverzeichnis: In der CI liegt er als Secret vor, und
was nie auf die Platte geschrieben wird, bleibt auch nicht versehentlich im
Workspace oder in einem Artefakt liegen. `--key-file` gibt es trotzdem — für
den Lauf von Hand auf der eigenen Maschine.

    tools/sign.py --payload defects.json --out defects.signed.json \
                  --key-id k1 --key-env SIGNING_KEY_PEM

Fehlt der Schlüssel, bricht das Skript ab. Ein unsigniertes `defects.json`
auszuliefern ist kein Rückfallpfad, sondern der Fehler, gegen den die ganze
Kette gebaut ist.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import envelope as env  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Defekt-Feed signieren")
    ap.add_argument("--payload", required=True,
                    help="Zu signierende Nutzdaten (defects.json).")
    ap.add_argument("--out", required=True,
                    help="Zieldatei für den Umschlag (defects.signed.json).")
    ap.add_argument("--key-id", default="k1",
                    help="keyId; bestimmt die Epoche. Vorgabe: k1.")
    quelle = ap.add_mutually_exclusive_group(required=True)
    quelle.add_argument("--key-env",
                        help="Name der Umgebungsvariablen mit dem PEM.")
    quelle.add_argument("--key-file",
                        help="PEM-Datei (nur für den Lauf von Hand).")
    args = ap.parse_args()

    if args.key_env:
        pem = os.environ.get(args.key_env, "")
        if not pem.strip():
            raise SystemExit(
                f"${args.key_env} ist leer oder nicht gesetzt — ohne Schlüssel "
                f"wird nicht veröffentlicht.")
        pem = pem.encode("utf-8")
    else:
        with open(args.key_file, "rb") as f:
            pem = f.read()

    try:
        key = env.load_private_key(pem)
    except Exception as exc:  # noqa: BLE001 — Ursache egal, Befund zählt
        # Bewusst ohne den Ausnahmetext: er kann Schlüsselmaterial enthalten
        # und landete sonst im öffentlichen CI-Log.
        raise SystemExit(f"Privater Schlüssel nicht ladbar ({type(exc).__name__}).")

    with open(args.payload, "rb") as f:
        payload = f.read()

    wrapped = env.wrap(payload, key, args.key_id)

    with open(args.out, "wb") as f:
        f.write(env.serialize(wrapped))

    print(f"→ {args.out} · keyId={args.key_id} · Epoche {wrapped['keyEpoch']} "
          f"· {len(payload)} Bytes signiert · Fingerabdruck {env.fingerprint(key)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
