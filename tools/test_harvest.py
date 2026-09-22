#!/usr/bin/env python3
"""Deterministischer Test: synthetische Fixture → erwarteter Feed.

Ohne pytest, wie die übrigen Skripte hier: `python3 tools/test_harvest.py`,
Exit 0 = grün.

Dieser Test ist das Gate vor dem Netzabruf. Er soll nicht "die Quelle" prüfen,
sondern verhindern, dass ein beschädigter Parser überhaupt die Gelegenheit
bekommt, den veröffentlichten Stand zu überschreiben — insbesondere der Fall,
in dem er still 0 statt der echten Einträge liefert.

Die Fixture ist erfunden (siehe ihren Kopf). Ein Abzug der echten Seite wäre
deren Mitveröffentlichung, und genau die schließt das README aus.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from harvest import clean, entry_id, harvest  # noqa: E402
from verify import check_coverage  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "synthetisch.html")


def main() -> int:
    html = open(FIXTURE, encoding="utf-8").read()
    buckets, extrakt = harvest(html)
    defects, notices, closures = buckets["defects"], buckets["notices"], buckets["closures"]

    # 1 — Beiwerk bleibt draußen. Greift der Selektor zu weit, stehen
    #     Navigation und Fließtext im Extrakt und damit in der Signatur.
    for fremd in ("Startseite", "Kontaktformular", "Falscher Selektor"):
        assert fremd not in extrakt, f"Beiwerk geerntet: {fremd!r}"

    # 2 — Defekte: nur die saubere "HWN <Nr> <kurzer Name>"-Liste.
    namen = {d["station"]: d["name"] for d in defects}
    assert set(namen) == {12, 13, 14}, set(namen)
    assert namen[12] == "Blauer Stein", repr(namen[12])
    # Soft-Hyphen und Zero-Width müssen weg sein, sonst wechselt die id täglich.
    assert namen[13] == "Musterklippe", repr(namen[13])
    # Zerfaserter Weißraum wird zu einfachen Leerzeichen geglättet.
    assert namen[14] == "Alte Hütte", repr(namen[14])

    # 3 — Hinweise: Freitext mit eingebetteter Nummer, beide Schreibweisen.
    hinweis_nummern = {n["station"] for n in notices}
    assert hinweis_nummern == {44, 45, 46}, hinweis_nummern
    # Fall 6: beginnt wie ein Defekt, ist aber zu lang für einen Namen.
    lang = next(n for n in notices if n["station"] == 46)
    assert lang["text"].startswith("HWN 46 Ein ungewöhnlich"), repr(lang["text"])

    # 4 — Sperrungen: ohne Nummer, plus die Nummer außerhalb des Bereichs.
    titel = {c["title"] for c in closures}
    assert "Beispielweg" in titel, titel
    assert "Der Rundweg am Musterteich ist bis auf Weiteres gesperrt." in titel, titel
    # Station 999 liegt über der Obergrenze 222: als Sperrung geführt, damit
    # der Meldungstext nicht stillschweigend verschwindet.
    assert "HWN 999 Hoher Zaun" in titel, titel
    assert 999 not in {d["station"] for d in defects}, "999 als Station durchgelassen"

    # 5 — Dubletten und leere Einträge.
    assert len(defects) == 3, [d["name"] for d in defects]
    assert len([z for z in extrakt.splitlines() if not z.strip()]) == 0, "Leerzeile im Extrakt"

    # 6 — severity ist rein kategoriebasiert, nie aus dem Text geraten.
    assert {d["severity"] for d in defects} == {"warning"}
    assert {n["severity"] for n in notices} == {"info"}
    assert {c["severity"] for c in closures} == {"critical"}

    # 7 — ids: Form, Eindeutigkeit, Stabilität.
    alle = defects + notices + closures
    ids = [e["id"] for e in alle]
    assert len(ids) == len(set(ids)), "doppelte id"
    assert all(len(i) == 12 and all(c in "0123456789abcdef" for c in i) for i in ids), ids
    # Derselbe Inhalt in anderer Schreibweise → dieselbe id. Das ist die
    # Zusage, auf die sich ein Client verlässt.
    assert entry_id("defects", "Blauer Stein") == entry_id("defects", " blauer  stein ")
    # Dieselbe Zeichenfolge in einer anderen Kategorie ist eine andere Aussage
    # und bekommt deshalb eine andere id.
    assert entry_id("defects", "Blauer Stein") != entry_id("closures", "Blauer Stein")
    # Ein zweiter Lauf liefert exakt dasselbe.
    nochmal, extrakt2 = harvest(html)
    assert [e["id"] for e in alle_nach(nochmal)] == ids, "Lauf nicht reproduzierbar"
    assert extrakt2 == extrakt, "Extrakt nicht reproduzierbar"

    # 8 — Deckung mit demselben Werkzeug, das auch Außenstehende benutzen:
    #     jeder Feedtext muss in einer Extraktzeile stehen.
    feed = {"defects": defects, "notices": notices, "closures": closures}
    erfunden, offen = check_coverage(feed, extrakt)
    assert not erfunden, f"Einträge ohne Entsprechung im Extrakt: {erfunden}"
    assert not offen, f"Extraktzeilen in keinem Eintrag: {offen}"

    # 9 — clean() für sich.
    assert clean("a­b​c") == "abc"
    assert clean("  viel\n\t Raum  ") == "viel Raum"

    print(f"PASS · {len(defects)} Defekte · {len(notices)} Hinweise · "
          f"{len(closures)} Sperrungen · {len(extrakt.splitlines())} Extraktzeilen")
    return 0


def alle_nach(buckets: dict) -> list:
    return [e for k in ("defects", "notices", "closures") for e in buckets[k]]


if __name__ == "__main__":
    raise SystemExit(main())
