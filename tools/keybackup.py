#!/usr/bin/env python3
"""Sicherung und Wiederherstellung der Signaturschlüssel.

Ein Ed25519-Schlüssel ist 32 Byte. Das sind 64 Hex-Zeichen — wenig genug, um
sie auf Papier zu schreiben, und Papier überlebt Dateiformate, Laufwerke und
Verschlüsselungswerkzeuge. Genau darum geht es hier: Die verschlüsselte Kopie
auf dem USB-Stick ist die bequeme Sicherung, der Zettel im Ordner ist die,
die in zehn Jahren noch lesbar ist.

    tools/keybackup.py export  --key ~/keys/k1.pem --key-id k1
    tools/keybackup.py restore --seed <64 Hex> --out k1-wieder.pem
    tools/keybackup.py check   --key ~/keys/k1.pem --expect <Fingerabdruck>

`export` gibt privates Schlüsselmaterial auf dem Bildschirm aus. Das ist der
Zweck, aber es heißt auch: nicht über eine Fernverbindung, nicht in einem
geteilten Fenster, und danach den Verlauf der Sitzung leeren. Die Ausgabe
gehört auf Papier, nicht in eine Datei und nicht in die Zwischenablage.

`check` ist der Teil, den man sonst vergisst. Eine Sicherung, die nie
zurückgespielt wurde, ist keine Sicherung, sondern eine Hoffnung. Der
Fingerabdruck ist der einzige Weg festzustellen, ob der zurückgespielte
Schlüssel wirklich der ist, mit dem der Feed signiert wurde.
"""

import argparse
import os
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import envelope as env  # noqa: E402


def _seed(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(serialization.Encoding.Raw,
                             serialization.PrivateFormat.Raw,
                             serialization.NoEncryption())


def _laden(pfad: str) -> Ed25519PrivateKey:
    with open(pfad, "rb") as f:
        return env.load_private_key(f.read())


def export(args) -> int:
    key = _laden(args.key)
    roh = _seed(key).hex()
    gruppen = " ".join(roh[i:i + 8] for i in range(0, len(roh), 8))

    print()
    print("  ┌─ ABSCHREIBEN UND SICHER VERWAHREN ─────────────────────────┐")
    print(f"  │  keyId         {args.key_id}")
    print(f"  │  Epoche        {env.KEY_EPOCHS.get(args.key_id, '?')}")
    print(f"  │  Fingerabdruck {env.fingerprint(key)}")
    print(f"  │  öffentlich    {env.public_raw(key).hex()}")
    print("  │")
    print("  │  privater Seed (64 Hex, 8er-Gruppen):")
    for i in range(0, len(gruppen), 45):
        print(f"  │      {gruppen[i:i + 45]}")
    print("  └────────────────────────────────────────────────────────────┘")
    print()
    print("  Zurückspielen:  tools/keybackup.py restore --seed <die 64 Hex ohne Leerzeichen> --out k1.pem")
    print("  Danach prüfen:  der Fingerabdruck muss derselbe sein wie oben.")
    print()
    print("  Diese Ausgabe steht jetzt im Verlauf deiner Sitzung. Terminal-Fenster")
    print("  schließen oder Verlauf leeren, sobald du sie abgeschrieben hast.")
    return 0


def restore(args) -> int:
    roh = "".join(args.seed.split()).lower()
    if len(roh) != 64 or any(c not in "0123456789abcdef" for c in roh):
        raise SystemExit("Der Seed muss aus genau 64 Hex-Zeichen bestehen "
                         f"(gelesen: {len(roh)}). Leerzeichen sind erlaubt.")
    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(roh))

    if os.path.exists(args.out):
        raise SystemExit(f"{args.out} existiert bereits — nicht überschrieben.")
    fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM,
                                  serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()))

    print(f"→ {args.out} geschrieben (Rechte 600)")
    print(f"  Fingerabdruck {env.fingerprint(key)}")
    print(f"  öffentlich    {env.public_raw(key).hex()}")
    print("  Stimmt der Fingerabdruck mit deiner Aufzeichnung überein, ist die "
          "Wiederherstellung gelungen.")
    return 0


def check(args) -> int:
    key = _laden(args.key)
    ist = env.fingerprint(key)
    if args.expect:
        if ist == args.expect.strip().lower():
            print(f"✓ Fingerabdruck stimmt: {ist}")
            return 0
        print(f"✗ Fingerabdruck weicht ab: erwartet {args.expect}, gelesen {ist}")
        return 1
    print(f"Fingerabdruck {ist}")
    print(f"öffentlich    {env.public_raw(key).hex()}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Signaturschlüssel sichern und zurückspielen")
    sub = ap.add_subparsers(dest="befehl", required=True)

    e = sub.add_parser("export", help="Seed und Fingerabdruck zum Abschreiben ausgeben.")
    e.add_argument("--key", required=True)
    e.add_argument("--key-id", default="k1")
    e.set_defaults(func=export)

    r = sub.add_parser("restore", help="Aus abgeschriebenem Seed ein PEM erzeugen.")
    r.add_argument("--seed", required=True)
    r.add_argument("--out", required=True)
    r.set_defaults(func=restore)

    c = sub.add_parser("check", help="Fingerabdruck eines PEM prüfen.")
    c.add_argument("--key", required=True)
    c.add_argument("--expect", help="Erwarteter Fingerabdruck (16 Hex).")
    c.set_defaults(func=check)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
