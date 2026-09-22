#!/usr/bin/env python3
"""PEM → die Zeile, die in `KEYS` gehört, plus Fingerabdruck.

Gedacht für den Rechner, auf dem der private Schlüssel entsteht — offline,
einmal. Das Skript gibt **nur** den öffentlichen Teil aus; der private
verlässt die Maschine nicht und wird hier auch nicht angefasst.

    tools/pubkey.py --key k1.pem --key-id k1

Der Fingerabdruck ist der Wert, den du an zwei Orten vergleichst: hier und im
Info-Bereich der App. Weichen sie voneinander ab, ist das ein Alarm und kein
Versehen, das man still anpasst.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import envelope as env  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Öffentlichen Schlüssel für KEYS ausgeben")
    ap.add_argument("--key", required=True,
                    help="PEM-Datei. Privat oder öffentlich — ausgegeben wird nur der öffentliche Teil.")
    ap.add_argument("--key-id", default="k1", help="keyId für die KEYS-Zeile.")
    args = ap.parse_args()

    with open(args.key, "rb") as f:
        pem = f.read()

    try:
        key = env.load_private_key(pem)
        herkunft = "privater Schlüssel"
    except Exception:  # noqa: BLE001 — dann eben als öffentlicher versuchen
        try:
            key = env.load_public_key(pem)
            herkunft = "öffentlicher Schlüssel"
        except Exception as exc:  # noqa: BLE001
            # Ohne Ausnahmetext: der kann Schlüsselmaterial enthalten.
            raise SystemExit(f"Nicht als Ed25519-Schlüssel lesbar ({type(exc).__name__}).")

    if args.key_id not in env.KEY_EPOCHS:
        raise SystemExit(f"keyId {args.key_id!r} hat keine Epoche in envelope.KEY_EPOCHS — "
                         f"bekannt: {', '.join(sorted(env.KEY_EPOCHS))}")

    print(f"# gelesen als {herkunft} · Epoche {env.KEY_EPOCHS[args.key_id]} · "
          f"Fingerabdruck {env.fingerprint(key)}")
    print(f"{args.key_id} {env.public_raw(key).hex()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
