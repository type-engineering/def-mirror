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
import time
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

# Der Selektor der aktuellen Seitenfassung (Stackable-Icon-Liste). Fragilste
# Zeile des ganzen Ernters: ein Theme-/Plugin-Wechsel bei der Quelle lässt ihn
# ins Leere laufen, und zwar ohne Fehler — er liefert dann einfach nichts.
PRIMARY_SELECTOR = "span.stk-block-icon-list-item__text"

# Ab wie vielen erkannten Stationsnummern gilt eine Ernte als plausibel. Die
# echte Seite führt rund ein Dutzend; drei sind niedrig genug, um eine
# ungewöhnlich kurze Liste durchzulassen, und hoch genug, damit ein
# Navigationsmenü oder eine Cookie-Leiste nicht als Treffer durchgeht.
MIN_STATION_HITS = 3

# Wartezeiten zwischen Abruf-Versuchen. Kurz genug, dass der Lauf nicht
# festhängt, lang genug für einen Neustart auf der Gegenseite.
RETRY_WAITS = (3, 10, 30)

_DEFECT_RE = re.compile(r"^HWN\s*(\d+)\s+(.+)$", re.IGNORECASE)
_NUMBER_RE = re.compile(r"(?:HWN|Stempelstelle(?:\s+Nummer)?)\s*(\d+)", re.IGNORECASE)

SEVERITY = {"defects": "warning", "notices": "info", "closures": "critical"}


class FetchError(RuntimeError):
    """Abruf endgültig fehlgeschlagen (nach allen Versuchen)."""


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


def _plausible(texts: list[str]) -> bool:
    """Sieht eine Ernte nach der gesuchten Liste aus?

    Einziges Kriterium ist die Zahl erkannter Stationsnummern. Bewusst nicht
    die Menge der Einträge: Ein Navigationsmenü hat auch zwanzig Punkte, aber
    keine Nummern.
    """
    return sum(1 for t in texts if _NUMBER_RE.search(t)) >= MIN_STATION_HITS


def _collect_lines(soup: BeautifulSoup) -> tuple[list[str], str]:
    """Die Eintragstexte einsammeln — mit Rückfallebenen.

    Drei Stufen, absteigend nach Genauigkeit. Jede wird nur genommen, wenn sie
    plausibel aussieht; sonst geht es zur nächsten. Zurück kommt auch, WELCHE
    Stufe gegriffen hat, damit `main()` eine Ernte über eine Rückfallebene
    sichtbar machen kann, statt sie unbemerkt wie eine normale zu behandeln.

    1. Der bekannte Selektor der aktuellen Seitenfassung.
    2. Listeneinträge aus jeder Liste, in der mindestens eine Stationsnummer
       vorkommt. Überspringt Navigation, Fußzeile und Cookie-Banner, ohne
       eine Klasse zu kennen — und überlebt damit einen Theme-Wechsel.
    3. Absätze und Tabellenzellen, die selbst eine Stationsnummer tragen.
       Letzte Reißleine: liefert die Hinweise, verliert aber die Sperrungen
       ohne Nummer.
    """
    direct = [clean(el.get_text(" ", strip=True)) for el in soup.select(PRIMARY_SELECTOR)]
    direct = [t for t in direct if t]
    if _plausible(direct):
        return direct, "selector"

    aus_listen: list[str] = []
    for liste in soup.find_all(["ul", "ol"]):
        eintraege = [clean(li.get_text(" ", strip=True)) for li in liste.find_all("li", recursive=False)]
        eintraege = [t for t in eintraege if t]
        if any(_NUMBER_RE.search(t) for t in eintraege):
            aus_listen.extend(eintraege)
    if _plausible(aus_listen):
        return aus_listen, "listen"

    frei = [clean(el.get_text(" ", strip=True)) for el in soup.find_all(["p", "td", "li"])]
    frei = [t for t in frei if t and _NUMBER_RE.search(t)]
    if _plausible(frei):
        return frei, "freitext"

    # Nichts Plausibles. Die beste vorhandene Ernte zurückgeben, damit der
    # Aufrufer sieht, was da war — er bricht daraufhin ab (oder übernimmt
    # explizit mit --allow-fallback).
    beste = max((direct, aus_listen, frei), key=len)
    return beste, "unplausibel"


def harvest(html: str) -> tuple[dict, str]:
    """HTML → (Kategorien, Quell-Extrakt).

    Der Extrakt ist die Liste der geernteten Zeilen in Dokumentreihenfolge,
    eine je Zeile, genau so wie sie in die Einordnung gegangen sind. Er ist
    bewusst *vor* der Klassifikation genommen: sonst prüfte Stufe 7 die
    Einordnung gegen sich selbst.
    """
    soup = BeautifulSoup(html, "html.parser")
    rohzeilen, strategie = _collect_lines(soup)

    zeilen: list[str] = []
    gesehen_zeile: set[str] = set()
    for text in rohzeilen:
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

    buckets["_strategy"] = strategie
    return buckets, "\n".join(zeilen) + "\n"


def previous_counts(out: str) -> dict[str, int] | None:
    """Kategorienzahlen des letzten guten Standes — oder `None` beim Erstlauf
    (Datei existiert noch nicht) bzw. wenn sie nicht lesbar ist."""
    try:
        with open(out, encoding="utf-8") as f:
            alt = json.load(f)
        return {k: len(alt.get(k, [])) for k in ("defects", "notices", "closures")}
    except (OSError, ValueError, AttributeError):
        return None


def shrink_verdict(neu: dict, alt: dict[str, int] | None, min_ratio: float) -> str | None:
    """Prüft die Ernte gegen den letzten guten Stand. Meldung oder `None`.

    Eine gefüllte Kategorie darf nicht auf null fallen, und die Gesamtzahl
    nicht unter einen Anteil des Vorstandes. Der zweite Teil fängt den Fall,
    den die Nullregel durchlässt — die halbe Ernte einer Rückfallebene.
    """
    if not alt:
        return None
    for kategorie in ("defects", "notices", "closures"):
        if alt[kategorie] > 0 and len(neu[kategorie]) == 0:
            return f"{kategorie} fällt von {alt[kategorie]} auf 0"
    alt_gesamt = sum(alt.values())
    neu_gesamt = sum(len(neu[k]) for k in ("defects", "notices", "closures"))
    if alt_gesamt and neu_gesamt < alt_gesamt * min_ratio:
        return f"Gesamtzahl fällt von {alt_gesamt} auf {neu_gesamt} (< {min_ratio:.0%})"
    return None


def fetch(url: str, attempts: int = len(RETRY_WAITS) + 1) -> bytes:
    """Holt die Seite, mit Wiederholung bei vorübergehenden Fehlern.

    Wiederholt wird bei Verbindungs- und Zeitfehlern, bei 5xx und bei 429
    (dann mit `Retry-After`, falls die Gegenseite eine Wartezeit nennt). NICHT
    wiederholt wird bei den übrigen 4xx: Ein 404 wird beim dritten Versuch
    auch nicht zu einer Seite, und hartnäckiges Nachfragen ist gegenüber
    einer fremden Seite unhöflich.
    """
    import requests  # nur im URL-Pfad nötig

    letzter = ""
    for versuch in range(attempts):
        if versuch:
            warte = RETRY_WAITS[min(versuch - 1, len(RETRY_WAITS) - 1)]
            print(f"  Versuch {versuch + 1}/{attempts} in {warte}s ({letzter})", file=sys.stderr)
            time.sleep(warte)
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
        except requests.RequestException as exc:
            letzter = type(exc).__name__
            continue

        if resp.status_code == 429 or resp.status_code >= 500:
            letzter = f"HTTP {resp.status_code}"
            nach = resp.headers.get("Retry-After")
            if nach and nach.isdigit():
                time.sleep(min(int(nach), 60))
            continue
        if resp.status_code >= 400:
            raise FetchError(f"HTTP {resp.status_code} — wird nicht wiederholt")

        return resp.content

    raise FetchError(f"nach {attempts} Versuchen aufgegeben ({letzter})")


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
    ap.add_argument("--min-ratio", type=float, default=0.5,
                    help="Schrumpf-Bremse: Mindestanteil der Eintragszahl des "
                         "letzten guten Standes (Vorgabe: 0.5). 0 schaltet sie ab.")
    ap.add_argument("--allow-fallback", action="store_true",
                    help="Ernte auch dann übernehmen, wenn sie auf einer "
                         "Rückfallebene entstand, weil der Selektor der "
                         "Quellseite nicht mehr greift.")
    args = ap.parse_args()

    if args.fixture:
        with open(args.fixture, "rb") as f:
            roh = f.read()
    else:
        try:
            roh = fetch(args.url)
        except FetchError as exc:
            print(f"FEHLER: Abruf fehlgeschlagen: {exc}. Lasse alten Stand stehen.",
                  file=sys.stderr)
            return 4

    html = roh.decode("utf-8", errors="replace")
    buckets, extrakt = harvest(html)
    strategie = buckets.pop("_strategy", "selector")

    gesamt = sum(len(buckets[k]) for k in ("defects", "notices", "closures"))
    if gesamt == 0:
        print(f"FEHLER: 0 Einträge geerntet (Ernte: {strategie}) — Layout der Quelle "
              "geändert? Der letzte gute Stand bleibt stehen.", file=sys.stderr)
        return 2

    # Eine Rückfallebene liefert Daten, aber nicht unbedingt vollständige:
    # Stufe 3 verliert die Sperrungen ohne Nummer. Das soll auffallen und nicht
    # stillschweigend den guten Stand ersetzen.
    if strategie != "selector":
        meldung = (f"Ernte über Rückfallebene {strategie!r} — der Selektor der "
                   f"Quellseite greift nicht mehr ({PRIMARY_SELECTOR}).")
        if args.allow_fallback:
            print(f"WARNUNG: {meldung} Übernommen, weil --allow-fallback gesetzt ist.",
                  file=sys.stderr)
        else:
            print(f"FEHLER: {meldung} Lasse alten Stand stehen; mit --allow-fallback "
                  "übernehmbar.", file=sys.stderr)
            return 2

    # Schrumpf-Bremse gegen den letzten guten Stand — vor dem Überschreiben
    # von args.out lesen, sonst vergleicht sie sich mit sich selbst.
    if args.min_ratio > 0:
        urteil = shrink_verdict(buckets, previous_counts(args.out), args.min_ratio)
        if urteil:
            print(f"FEHLER: Schrumpf-Bremse — {urteil}. Lasse alten Stand stehen.",
                  file=sys.stderr)
            return 5

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
          f"· Ernte {strategie} → {args.out}, {args.source_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
