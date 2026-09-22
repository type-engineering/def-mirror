# Sicherheitshinweise und Schwachstellenmeldung

Dieses Repository veröffentlicht einen signierten Datensatz. Wenn du einen
Fehler in der Signaturkette, im Prüfwerkzeug oder in den veröffentlichten Daten
findest, ist eine Meldung willkommen.

## Melden

**E-Mail:** `type.engineering@posteo.de` — gern mit dem Betreff
`[def-mirror] <kurze Beschreibung>`.

Hilfreich ist, was den Befund nachvollziehbar macht: betroffene Datei oder
Endpunkt, beobachtetes Verhalten, erwartetes Verhalten, und wenn möglich die
Schritte oder der Commit, an dem es auftritt.

Bitte **keine** öffentlichen Issues für Befunde, die sich ausnutzen lassen,
bevor sie behoben sind. Für alles andere — unklare Dokumentation, ein Feld, das
nicht zum Schema passt, ein Prüfwerkzeug, das nicht läuft — ist ein Issue genau
richtig.

## Meldungen

| Schritt | Ziel |
|---|---|
| Eingangsbestätigung | 7 Tage |
| Erste Einschätzung (betrifft es die Auslieferung?) | 14 Tage |
| Behebung oder ein begründeter Plan | 90 Tage |
| Öffentliche Darstellung nach Behebung | im Commit, auf Wunsch mit Namensnennung |

Meldungen, die die **Integrität der Auslieferung** betreffen — Signaturprüfung,
Schlüsselbehandlung, Möglichkeiten, einem Client einen falschen oder alten Stand
unterzuschieben — werden vorgezogen.

## Geltungsbereich

**Im Geltungsbereich:**

- Die veröffentlichten Artefakte (`defects.json`, `defects.signed.json`,
  `defects-source.txt`) und ihre Übereinstimmung untereinander.
- `tools/verify.py` und `tools/envelope.py`, einschließlich Fällen, in denen ein
  manipuliertes Dokument fälschlich als gültig durchgeht.
- Die Schemata und die Frage, ob ein schemakonformes Dokument einen Client in
  einen unerwünschten Zustand bringen kann.
- Die in `KEYS` veröffentlichten Schlüssel und ihre Fingerabdrücke.

**Außerhalb:**

- Die Quellseite, deren Inhalt hier gespiegelt wird. Fehler *in den Meldungen*
  gehören zu ihrem Betreiber.
- Die Infrastruktur des Hosters.
- Befunde, die allein aus einer automatischen Prüfung stammen, ohne dass ein
  konkreter Angriffsweg beschrieben ist.

## Bekannte, bewusst getragene Grenzen

Diese Punkte sind **keine** Schwachstellen, sondern dokumentierte
Entwurfsentscheidungen. Eine Meldung dazu ist trotzdem nicht falsch — aber sie
wird auf diesen Abschnitt verweisen:

1. **Die erzeugende Pipeline signiert selbst.** Wer sie übernimmt, signiert
   mit. Dagegen wirken die öffentliche Commit-Historie, der beiliegende
   Quell-Extrakt und die Prüfungen auf der Client-Seite — nicht die
   Signatur.
2. **Kein Widerrufsserver.** Der Widerruf läuft über die aufsteigende
   `keyEpoch`. Ein Gerät, dessen Netzverkehr dauerhaft kontrolliert wird,
   erfährt davon nichts; dagegen hilft nur ein Client-Update. Siehe README,
   Abschnitt „Schlüssel, Epochen, Widerruf".
3. **Die Klassifikation der Einträge ist eine Heuristik.** Eine Signatur
   beglaubigt auch eine Fehlklassifikation. Genau deshalb liegt der
   Quell-Extrakt bei — und die Deckungsprüfung zeigt, was er hergibt.
4. **Zugriffsmetadaten.** Ein Abruf übergibt dem Hoster IP-Adresse und
   Zeitpunkt. Das ist bei jeder HTTPS-Auslieferung so und nicht abschaltbar;
   der Abruf selbst trägt darüber hinaus nichts (keine Kennung, keine
   Query-Parameter, kein versionsbehafteter User-Agent).

## Selbst prüfen

Bevor du meldest, lohnt ein Prüflauf — er beantwortet die meisten Fragen von
selbst:

```bash
python3 -m venv .venv && .venv/bin/pip install -r tools/requirements.txt
.venv/bin/python tools/verify.py --envelope defects.signed.json --keys KEYS \
    --expect-json defects.json --source defects-source.txt
```

Schlägt eine Stufe fehl, obwohl die Artefakte frisch aus diesem Repository
stammen, ist das genau der Fall, den wir hören wollen.
