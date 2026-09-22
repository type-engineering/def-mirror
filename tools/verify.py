#!/usr/bin/env python3
"""Prüfwerkzeug für den veröffentlichten Defekt-Feed — für jeden, nicht nur für den Herausgeber.

Eine Signatur, die nur der Herausgeber prüfen kann, ist Dekoration. Dieses
Skript ist absichtlich klein, hängt nur an `cryptography` (plus optional
`jsonschema`) und hat keinen Bezug zu einer App: Wer wissen will, ob die Daten
auf seinem Gerät die veröffentlichten sind, lädt sie und prüft selbst.

    python3 verify.py --url https://<host>/defects.signed.json --keys KEYS
    python3 verify.py --envelope defects.signed.json --key k1=<64 Hex>
    python3 verify.py --envelope defects.signed.json --keys KEYS \
                      --expect-json defects.json --source defects-source.txt

Geprüft wird in Stufen, jede für sich aussagekräftig:

  1. Umschlag wohlgeformt, `alg`/`envelopeVersion` wie erwartet.
  2. Signatur gültig unter dem Schlüssel zur genannten `keyId`. Unbekannte
     keyId = Fehler. Genau so wirkt ein Widerruf.
  3. Nutzdaten gültig nach `defects.schema.json`.
  4. `validUntil` noch nicht verstrichen (nur Hinweis, kein Fehlschlag — ein
     alter Stand ist nicht gefälscht, nur alt).
  5. Optional: Nutzdaten Byte für Byte identisch mit der lesbar
     veröffentlichten `defects.json`.
  6. Optional: `extractSha256` passt zum veröffentlichten Quell-Extrakt.
  7. Optional: **Deckung** — jeder Text im Feed steht so auch im Extrakt, und
     es wird gemeldet, wie viele Extraktzeilen in keinem Eintrag auftauchen.

Stufe 7 ist die interessante: Sie beantwortet „wurde hier etwas erfunden oder
weggelassen?", ohne den Parser des Herausgebers zu kennen oder zu brauchen.
Die Signatur allein beglaubigt auch eine Fehleinordnung.

Exit 0 = alles grün. Exit 1 = mindestens eine Prüfung gescheitert.
"""

import argparse
import binascii
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import envelope as env  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = os.path.join(HERE, "defects.schema.json")


def _load_key_spec(spec: str):
    """`k1=<64 Hex>` oder `k1=pfad/zur/datei.pem|.raw` → (keyId, PublicKey)."""
    if "=" not in spec:
        raise SystemExit(f"--key erwartet keyId=WERT, bekam {spec!r}")
    key_id, value = spec.split("=", 1)
    if os.path.exists(value):
        with open(value, "rb") as f:
            return key_id, env.load_public_key(f.read())
    try:
        return key_id, env.load_public_key(binascii.unhexlify(value))
    except (binascii.Error, ValueError) as exc:
        raise SystemExit(f"--key {key_id}: weder Datei noch 64 Hex-Zeichen") from exc


def _load_keys_file(path: str) -> dict:
    """KEYS-Datei: je Zeile `<keyId> <64 Hex>`, `#` ist Kommentar.

    Das ist das veröffentlichte Vertrauensanker-Dokument. Es liegt im
    öffentlichen Repo, und seine Einführung steht datiert in der
    Commit-Historie — ein nachträglich untergeschobener Schlüssel müsste diese
    Historie umschreiben, was für jeden sichtbar ist, der eine Kopie hat.
    """
    keys = {}
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 2:
                raise SystemExit(f"{path}:{lineno}: erwartet `<keyId> <64 Hex>`")
            key_id, hexval = parts
            try:
                keys[key_id] = env.load_public_key(binascii.unhexlify(hexval))
            except (binascii.Error, ValueError) as exc:
                raise SystemExit(f"{path}:{lineno}: kein gültiger Schlüssel") from exc
    if not keys:
        raise SystemExit(f"{path}: keine Schlüssel gefunden")
    return keys


def _fetch(url: str) -> bytes:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "def-mirror-verify/1"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 — vom Nutzer genannte URL
        return resp.read()


def feed_texts(feed: dict) -> list[str]:
    """Alle Texte, die der Feed behauptet — in der Form, in der sie dort stehen."""
    texte = [e.get("name", "") for e in feed.get("defects", [])]
    texte += [e.get("text", "") for e in feed.get("notices", [])]
    texte += [e.get("title", "") for e in feed.get("closures", [])]
    return [t for t in texte if t]


def check_coverage(feed: dict, extrakt: str) -> tuple[list[str], list[str]]:
    """Deckung zwischen Feed und Quell-Extrakt.

    Zurück kommen (erfunden, unberücksichtigt):

    * **erfunden** — Feedtexte, die in keiner Extraktzeile vorkommen. Das wäre
      der schwere Fall: eine Meldung, die die Quelle nie gemacht hat.
    * **unberücksichtigt** — Extraktzeilen, die in keinem Eintrag auftauchen.
      Meist harmlos (Überschriften, Beiwerk), aber der Ort, an dem eine
      weggelassene Meldung sichtbar würde.

    Verglichen wird per Teilzeichenkette, nicht auf Gleichheit: Bei einem
    Defekt steht im Feed nur der Name, in der Zeile zusätzlich die Nummer.
    """
    zeilen = [z for z in extrakt.splitlines() if z.strip()]
    offen = list(zeilen)
    erfunden = []
    for text in feed_texts(feed):
        treffer = next((z for z in zeilen if text in z), None)
        if treffer is None:
            erfunden.append(text)
        elif treffer in offen:
            offen.remove(treffer)
    return erfunden, offen


def main() -> int:
    ap = argparse.ArgumentParser(description="Signierten Defekt-Feed prüfen")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--envelope", help="Lokale defects.signed.json.")
    src.add_argument("--url", help="URL der defects.signed.json.")
    ap.add_argument("--key", action="append", default=[],
                    help="keyId=<64 Hex> oder keyId=<Datei>. Mehrfach möglich.")
    ap.add_argument("--keys", help="KEYS-Datei mit `<keyId> <64 Hex>` je Zeile.")
    ap.add_argument("--expect-json", help="Lesbare defects.json für den Byte-Vergleich.")
    ap.add_argument("--source", help="Quell-Extrakt (defects-source.txt) für Stufe 6 und 7.")
    ap.add_argument("--min-epoch", type=int, default=0,
                    help="Höchste bereits gesehene keyEpoch; niedrigere gelten als widerrufen.")
    ap.add_argument("--out", help="Geprüften Feed hierhin schreiben (nur bei Erfolg).")
    args = ap.parse_args()

    keys = _load_keys_file(args.keys) if args.keys else {}
    for spec in args.key:
        key_id, key = _load_key_spec(spec)
        keys[key_id] = key
    if not keys:
        raise SystemExit("Kein öffentlicher Schlüssel angegeben (--keys oder --key).")

    raw = _fetch(args.url) if args.url else open(args.envelope, "rb").read()
    wrapped = json.loads(raw)

    fehler = []

    # 1 + 2 — Umschlag und Signatur.
    try:
        payload = env.unwrap(wrapped, keys, min_epoch=args.min_epoch)
        print(f"✓ Signatur gültig · keyId={wrapped.get('keyId')} · "
              f"Epoche {wrapped.get('keyEpoch')} · {len(payload)} Bytes Nutzdaten")
    except env.SigningError as exc:
        print(f"✗ Signatur: {exc}")
        return 1  # ohne gültige Signatur ist jede weitere Aussage wertlos

    feed = json.loads(payload)

    # 3 — Schema.
    try:
        import jsonschema
        jsonschema.Draft202012Validator(json.load(open(SCHEMA, encoding="utf-8"))).validate(feed)
        print("✓ Nutzdaten entsprechen defects.schema.json")
    except ImportError:
        print("· jsonschema nicht installiert — Schemaprüfung übersprungen")
    except Exception as exc:  # noqa: BLE001 — Validierungsfehler jeder Ausprägung
        fehler.append(f"Schema: {exc}")
        print(f"✗ Schema: {str(exc).splitlines()[0]}")

    # 4 — Frische. Ein abgelaufener Stand ist nicht gefälscht, nur alt.
    try:
        gueltig_bis = datetime.fromisoformat(feed["validUntil"])
        rest = gueltig_bis - datetime.now(timezone.utc)
        if rest.total_seconds() < 0:
            print(f"· abgelaufen seit {-rest.days} Tagen (validUntil {feed['validUntil']})")
        else:
            print(f"✓ gültig noch {rest.days} Tage (bis {feed['validUntil']})")
    except (KeyError, ValueError) as exc:
        fehler.append(f"validUntil: {exc}")
        print(f"✗ validUntil unlesbar: {exc}")

    # 5 — Byte-Gleichheit mit der lesbaren Veröffentlichung.
    if args.expect_json:
        lesbar = open(args.expect_json, "rb").read()
        if lesbar == payload:
            print("✓ defects.json Byte für Byte identisch mit den signierten Nutzdaten")
        else:
            fehler.append("defects.json weicht von den signierten Nutzdaten ab")
            print("✗ defects.json weicht von den signierten Nutzdaten ab")

    # 6 + 7 — Ableitung aus dem Quell-Extrakt.
    if args.source:
        extrakt = open(args.source, encoding="utf-8").read()
        erwartet = feed.get("extractSha256")
        tatsächlich = hashlib.sha256(extrakt.encode("utf-8")).hexdigest()
        if not erwartet:
            fehler.append("extractSha256 fehlt im Feed")
            print("✗ extractSha256 fehlt im Feed")
        elif erwartet == tatsächlich:
            print(f"✓ Quell-Extrakt passt (sha256 {tatsächlich[:16]}…)")
        else:
            fehler.append("extractSha256 passt nicht zum Extrakt")
            print(f"✗ Extrakt: Feed nennt {erwartet[:16]}…, Datei ist {tatsächlich[:16]}…")

        erfunden, offen = check_coverage(feed, extrakt)
        if erfunden:
            fehler.append(f"{len(erfunden)} Eintrag/Einträge ohne Entsprechung im Extrakt")
            print(f"✗ Deckung: {len(erfunden)} Eintrag/Einträge stehen in keiner Extraktzeile")
            for text in erfunden[:3]:
                print(f"    {text[:70]}")
        else:
            print(f"✓ Deckung: alle {len(feed_texts(feed))} Einträge stehen so im Extrakt")
        if offen:
            print(f"· {len(offen)} Extraktzeile(n) in keinem Eintrag verwendet "
                  f"(meist Beiwerk — hier würde eine weggelassene Meldung auffallen)")

    if fehler:
        print(f"\nFEHLGESCHLAGEN · {len(fehler)} Prüfung(en): " + "; ".join(fehler))
        return 1

    if args.out:
        with open(args.out, "wb") as f:
            f.write(payload)
        print(f"→ geprüften Feed geschrieben: {args.out}")
    print("\nOK · alle Prüfungen bestanden")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
