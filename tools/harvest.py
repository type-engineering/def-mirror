#!/usr/bin/env python3
"""Quellseite ernten → `defects.json` (Schema 2) + `defects-source.txt`.

Die Klassifikationslogik stammt aus dem erprobten Parser des internen
Spiegels (`tools/defect-mirror/parse.py`) und ist inhaltsbasiert, nicht
positionsbasiert: die Spaltenstruktur der Quelle ordnet Listen nicht
verlässlich ihren Überschriften zu, der Textinhalt schon.

Gegenüber jenem Parser kommt hinzu, was Schema 2 und die Prüfstufen 6 und 7
verlangen:

* **Quell-Extrakt.** Die geernteten Zeilen *vor* der Einordnung werden
  mitveröffentlicht. Erst dadurch ist die Einordnung von außen prüfbar:
  `verify.py` vergleicht jeden Feedtext gegen diese Zeilen und meldet
  Erfundenes wie Weggelassenes.
* **Stabile `id`.** 12 Hex aus dem Inhalt, normalisiert über NFKC und
  Weißraum — derselbe Eintrag hat morgen dieselbe id, auch wenn die Quelle
  ihre Liste umsortiert oder neu formatiert.
* **`severity` rein kategoriebasiert.** closures → critical, defects →
  warning, notices → info. Die Einordnung ist bereits eine Heuristik und
  bekommt keine zweite obendrauf.
* **`validUntil`.** Ab da gilt der Zustand als unbekannt, nicht als "in
  Ordnung".

    tools/harvest.py --out defects.json --source-out defects-source.txt
    tools/harvest.py --fixture seite.html --out …     # offline, für Tests

Liefert der Parse null Einträge über alle Kategorien, bricht das Skript mit
Exit 2 ab und lässt den letzten guten Stand stehen: ein stilles Redesign der
Quelle darf den Datensatz nicht leerräumen. "Keine Meldungen" liest sich wie
"alles in Ordnung" und ist der gefährlichste Fehler dieses Feeds.
"""

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup

SOURCE_URL = "https://www.harzer-wandernadel.de/defektmeldungen/"
USER_AGENT = ("def-mirror/1.0 (+https://github.com/type-engineering/def-mirror; "
              "taeglicher Spiegel, ein Abruf pro Tag)")

# Obergrenze des Nummernraums, wie in defects.schema.json festgeschrieben.
STATION_MAX = 222

# Ein „Defekt" hat einen kurzen Namen; längere Texte sind Hinweis-Sätze.
DEFECT_NAME_MAX_WORDS = 4

_DEFECT_RE = re.compile(r"^HWN\s*(\d+)\s+(.+)$", re.IGNORECASE)
_NUMBER_RE = re.compile(r"(?:HWN|Stempelstelle(?:\s+Nummer)?)\s*(\d+)", re.IGNORECASE)

SEVERITY = {"defects": "warning", "notices": "info", "closures": "critical"}


def clean(text: str) -> str:
    """Soft-Hyphens und Zero-Width-Zeichen raus, Unicode normalisieren,
    Weißraum glätten. Ohne das unterscheiden sich zwei optisch gleiche Zeilen
    in den Bytes, und der Feed meldet jeden Tag „neue" Einträge."""
    text = unicodedata.normalize("NFC", text)
    for ch in ("­", "​", "‌", "‍", "﻿"):
        text = text.replace(ch, "")
    return re.sub(r"\s+", " ", text).strip()


def entry_id(kind: str, text: str) -> str:
    """Inhaltsabgeleitete, stabile Kennung (12 Hex).

    NFKC statt NFC wie beim Reinigen: Hier geht es nicht um die Darstellung,
    sondern um Gleichheit. Typografische Varianten desselben Zeichens sollen
    auf dieselbe id fallen, damit ein Reformat der Quelle einen bekannten
    Eintrag nicht als „neu" zurückbringt. Die Kategorie geht mit ein — derselbe
    Text in einer anderen Rolle ist eine andere Aussage.
    """
    kanonisch = unicodedata.normalize("NFKC", text).casefold()
    kanonisch = re.sub(r"\s+", " ", kanonisch).strip()
    roh = f"{kind}\x1f{kanonisch}".encode("utf-8")
    return hashlib.sha256(roh).hexdigest()[:12]


def classify(text: str) -> tuple[str, dict]:
    """Einen bereinigten Eintragstext einer Kategorie zuordnen.

    Eine Stationsnummer außerhalb von 1…{STATION_MAX} ist laut Schema ein
    Parse-Fehler und keine Station. Der Eintrag wird deshalb nicht verworfen,
    sondern als `closure` geführt: der Meldungstext bleibt veröffentlicht, nur
    der Join-Key fehlt. Stilles Wegwerfen wäre die schlechtere Wahl — es
    verschwände eine Meldung, die die Quelle gemacht hat.
    """
    m = _DEFECT_RE.match(text)
    if m and len(m.group(2).split()) <= DEFECT_NAME_MAX_WORDS:
        station = int(m.group(1))
        if 1 <= station <= STATION_MAX:
            return "defects", {"station": station, "name": m.group(2).strip()}
        print(f"· Station {station} außerhalb 1…{STATION_MAX} — als Sperrung geführt: "
              f"{text[:60]}", file=sys.stderr)
        return "closures", {"title": text}

    n = _NUMBER_RE.search(text)
    if n:
        station = int(n.group(1))
        if 1 <= station <= STATION_MAX:
            return "notices", {"station": station, "text": text}
        print(f"· Station {station} außerhalb 1…{STATION_MAX} — als Sperrung geführt: "
              f"{text[:60]}", file=sys.stderr)
        return "closures", {"title": text}

    return "closures", {"title": text}


def harvest(html: str) -> tuple[dict, str]:
    """HTML → (Kategorien, Quell-Extrakt).

    Der Extrakt ist die Liste der geernteten Zeilen in Dokumentreihenfolge,
    eine je Zeile, genau so wie sie in die Einordnung gegangen sind. Er ist
    bewusst *vor* der Klassifikation genommen: sonst prüfte Stufe 7 die
    Einordnung gegen sich selbst.
    """
    soup = BeautifulSoup(html, "html.parser")
    spans = soup.select("span.stk-block-icon-list-item__text")

    zeilen: list[str] = []
    gesehen_zeile: set[str] = set()
    for span in spans:
        text = clean(span.get_text(" ", strip=True))
        if not text or text in gesehen_zeile:
            continue
        gesehen_zeile.add(text)
        zeilen.append(text)

    buckets: dict[str, list] = {"defects": [], "notices": [], "closures": []}
    gesehen_id: set[str] = set()
    for text in zeilen:
        kategorie, eintrag = classify(text)
        kennung = entry_id(kategorie, eintrag.get("name") or eintrag.get("text")
                           or eintrag.get("title", ""))
        if kennung in gesehen_id:
            continue
        gesehen_id.add(kennung)
        buckets[kategorie].append(
            {"id": kennung, "severity": SEVERITY[kategorie], **eintrag})

    return buckets, "\n".join(zeilen) + "\n"


def fetch(url: str) -> bytes:
    import requests  # nur im URL-Pfad nötig

    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    return resp.content


def main() -> int:
    ap = argparse.ArgumentParser(description="Defektmeldungen ernten → Schema 2")
    ap.add_argument("--out", default="defects.json", help="Zieldatei für die Nutzdaten.")
    ap.add_argument("--source-out", default="defects-source.txt",
                    help="Zieldatei für den Quell-Extrakt.")
    ap.add_argument("--fixture", help="Lokale HTML-Datei statt Abruf (Tests).")
    ap.add_argument("--url", default=SOURCE_URL, help="Abweichende Quell-URL.")
    ap.add_argument("--valid-days", type=int, default=7,
                    help="Gültigkeitsdauer ab generatedAt in Tagen (Vorgabe: 7).")
    ap.add_argument("--generated-at", default=None,
                    help="ISO-Zeitstempel überschreiben (Tests, reproduzierbare Läufe).")
    args = ap.parse_args()

    if args.fixture:
        with open(args.fixture, "rb") as f:
            roh = f.read()
    else:
        roh = fetch(args.url)

    html = roh.decode("utf-8", errors="replace")
    buckets, extrakt = harvest(html)

    gesamt = sum(len(v) for v in buckets.values())
    if gesamt == 0:
        print("FEHLER: 0 Einträge geerntet — Layout der Quelle geändert? "
              "Der letzte gute Stand bleibt stehen.", file=sys.stderr)
        return 2

    if args.generated_at:
        erzeugt = datetime.fromisoformat(args.generated_at)
    else:
        erzeugt = datetime.now(timezone.utc).replace(microsecond=0)

    feed = {
        "schemaVersion": 2,
        "generatedAt": erzeugt.isoformat(),
        "validUntil": (erzeugt + timedelta(days=args.valid_days)).isoformat(),
        "source": args.url,
        "sourceSha256": hashlib.sha256(roh).hexdigest(),
        "extractSha256": hashlib.sha256(extrakt.encode("utf-8")).hexdigest(),
        **buckets,
    }

    with open(args.source_out, "w", encoding="utf-8") as f:
        f.write(extrakt)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(feed, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"OK: {len(buckets['defects'])} Defekte · {len(buckets['notices'])} Hinweise · "
          f"{len(buckets['closures'])} Sperrungen · {len(extrakt.splitlines())} Extraktzeilen "
          f"→ {args.out}, {args.source_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
