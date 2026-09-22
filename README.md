# def-mirror

Ein täglich gespiegelter, **signierter** Statusdatensatz: Meldungen über defekte
Stationen, sicherheitsrelevante Hinweise und Wegsperrungen einer öffentlichen Quellseite, maschinell
in ein stabiles JSON-Schema überführt und hier veröffentlicht.

Zweck des Repositorys ist nicht die Auslieferung, sondern die
**Nachvollziehbarkeit**: Jeder ausgelieferte Stand liegt als datierter Commit
vor, zusammen mit der Signatur und einem Extrakt der Quellzeilen, aus denen er
entstanden ist. Wer den Datensatz nutzt, muss dem Herausgeber nicht glauben — er
kann nachrechnen.

## Artefakte

| Datei | Inhalt |
|---|---|
| `defects.json` | die Nutzdaten, lesbar, Schema 2 |
| `defects.signed.json` | dieselben Bytes im signierten Umschlag — **das, was Clients abrufen** |
| `defects-source.txt` | Quell-Extrakt: die geernteten Zeilen vor der Einordnung |
| `KEYS` | die öffentlichen Schlüssel (Vertrauensanker) |
| `tools/` | Prüfwerkzeug und Schemata |

Clients holen ausschließlich `defects.signed.json`. Ein Abruf, ein Dokument:
Bei zwei getrennten Dateien (Daten + Signatur daneben) kann zwischen den beiden
Anfragen veröffentlicht werden, und der Client hält neue Daten mit alter
Signatur in der Hand.

## Prüfen

```bash
python3 -m venv .venv && .venv/bin/pip install -r tools/requirements.txt
.venv/bin/python tools/verify.py --envelope defects.signed.json --keys KEYS \
    --expect-json defects.json --source defects-source.txt
```

Geprüft wird in Stufen, jede für sich aussagekräftig:

1. **Umschlag** wohlgeformt, Verfahren und Version wie erwartet.
2. **Signatur** gültig unter dem Schlüssel zur genannten `keyId`. Eine
   unbekannte `keyId` ist ein Fehler, kein Grund zum Raten — genau so wirkt ein
   Widerruf.
3. **Schema**: die Nutzdaten entsprechen `tools/defects.schema.json`.
4. **Frische**: `validUntil` noch nicht verstrichen. Nur ein Hinweis, kein
   Fehlschlag — ein alter Stand ist nicht gefälscht, nur alt.
5. **Byte-Gleichheit**: die lesbare `defects.json` ist Byte für Byte das, was
   signiert wurde.
6. **Herkunft**: `extractSha256` passt zum mitveröffentlichten Quell-Extrakt.
7. **Deckung**: jeder Text im Feed steht so auch im Extrakt, und es wird
   gemeldet, wie viele Extraktzeilen in keinem Eintrag auftauchen.

Stufe 7 ist die interessante. Sie beantwortet „wurde hier etwas erfunden oder
weggelassen?“ — ohne den Parser des Herausgebers zu kennen oder zu brauchen.
Ein erfundener Eintrag lässt die Prüfung scheitern; eine weggelassene Meldung
bleibt als unberücksichtigte Extraktzeile stehen.

Exit 0 heißt: alle Stufen bestanden.

Ohne Argumente prüft das Werkzeug nur, was es kann; `--expect-json` und
`--source` sind optional, aber sie sind der interessante Teil. Ein Abruf direkt
gegen die ausgelieferte URL geht auch:

```bash
.venv/bin/python tools/verify.py --url <URL>/defects.signed.json --keys KEYS
```

## Schema 2 — `defects.json`

Maschinenlesbar: `tools/defects.schema.json` (JSON Schema 2020-12). In Worten:

```json
{
  "schemaVersion": 2,
  "generatedAt": "2026-09-22T06:00:00+00:00",
  "validUntil":  "2026-09-29T06:00:00+00:00",
  "source": "https://www.harzer-wandernadel.de/defektmeldungen/",
  "sourceSha256": "bb262d0eb0a81d0e231c05b83a681793e4f6eb6b4c428fcc5a19a78183b58ef1",
  "extractSha256": "8c818f7eff40cf5b8cf58e76b01fc6d089191bbf4ed9652a2e00b950c235cc16",
  "defects":  [ { "id": "3b12857260d9", "severity": "warning",  "station": 90, "name": "Roter Schuss" } ],
  "notices":  [ { "id": "6c77f1668ef1", "severity": "info",     "station": 163, "text": "Die Stempelstelle 163 Bremerklippe wurde 2,7 Kilometer entfernt an den Kaiserweg versetzt." } ],
  "closures": [ { "id": "ac6c80bb6fcb", "severity": "critical", "title": "WaldWandelWeg" } ]
}
```

Die Werte oben sind echt und nachrechenbar, nicht illustrativ: Die ids fallen
aus `tools/harvest.py` genau so heraus, und wer den Extrakt hat, bekommt
denselben `extractSha256`.

### Kopf

| Feld | Typ | Bedeutung |
|---|---|---|
| `schemaVersion` | `2` | Hauptversion. Ein neues Pflichtfeld oder ein geänderter Typ verlangt eine neue Version — ausgelieferte Clients lesen den alten Stand weiter. |
| `generatedAt` | ISO-8601 | Zeitpunkt des Laufs. Clients sollten einen Stand ablehnen, der **nicht neuer** ist als ihr vorhandener (Schutz gegen das Wiedereinspielen alter Stände). |
| `validUntil` | ISO-8601 | Ab hier darf kein Zustand mehr behauptet werden — der Status gilt als *unbekannt*. Die Frist gehört den Daten, nicht dem Client-Binary. |
| `source` | URL | Seite, aus der dieser Stand entstand. |
| `sourceSha256` | 64 Hex | SHA-256 der abgerufenen Quellseite. Die Seite selbst wird nicht mitveröffentlicht — wer sie abruft, kann vergleichen. |
| `extractSha256` | 64 Hex | SHA-256 des Quell-Extrakts. Bindeglied zwischen Daten und `defects-source.txt`. |

### Die drei Kategorien

Klassifiziert wird **inhaltsbasiert**, nicht nach der Position auf der
Quellseite — deren Aufbau ordnet Listen nicht verlässlich ihren Überschriften zu.

| Kategorie | Wann | Felder |
|---|---|---|
| `defects` | Eintrag mit Stationsnummer und kurzem Namen | `id`, `severity`, `station`, `name` |
| `notices` | Freitext mit eingebetteter Stationsnummer | `id`, `severity`, `station`, `text` |
| `closures` | Eintrag ohne jede Stationsnummer | `id`, `severity`, `title` |

### Felder je Eintrag

| Feld | Typ | Bedeutung |
|---|---|---|
| `id` | 12 Hex | Stabile, **inhaltsabgeleitete** Kennung: derselbe Eintrag hat morgen dieselbe `id`, unabhängig von seiner Position in der Liste. Normalisiert über NFKC und Weißraum, damit ein Reformat der Quelle einen bekannten Eintrag nicht als „neu" zurückbringt. |
| `severity` | `info` \| `warning` \| `critical` | **Rein kategoriebasiert**, nicht aus dem Text geraten: `closures` → `critical`, `defects` → `warning`, `notices` → `info`. Die Klassifikation ist bereits eine Heuristik und bekommt keine zweite obendrauf. |
| `station` | 1…222 | Nummer der Station, auf die sich der Eintrag bezieht. Join-Key auf der Client-Seite. |
| `name` / `text` / `title` | String | Der Meldungstext. Clients sollten ihn als **reinen Text** darstellen — kein Markdown, keine automatische Link-Erkennung. |

## Umschlagformat — `defects.signed.json`

Maschinenlesbar: `tools/envelope.schema.json`.

```json
{
  "envelopeVersion": 1,
  "alg": "ed25519",
  "keyId": "k1",
  "keyEpoch": 1,
  "payload": "<Base64 der exakten Bytes von defects.json>",
  "sig": "<Base64 der Ed25519-Signatur>"
}
```

Signiert werden die **rohen Bytes** der Nutzdaten, nicht deren
Base64-Darstellung. Die Prüfkette lautet damit:

```
base64decode(payload) == bytes(defects.json)
ed25519_verify(pubkey[keyId], sig, jene Bytes)
```

## Schlüssel, Epochen, Widerruf

Ed25519, ein aktiver Schlüssel und eine Reserve. Kein CA, kein
Widerrufsserver, keine Ablaufdaten. Die privaten Schlüssel entstehen von Hand
und offline; sie liegen in keinem Repository und in keiner Cloud.

`keyEpoch` ist der Widerruf. Ein zweiter Schlüssel im Client allein widerruft
nichts — der Client vertraut dann eben beiden, und wer den ersten gestohlen hat,
signiert weiter gültig. Deshalb trägt jeder Umschlag eine aufsteigende Epoche.

> **Clients merken sich die höchste Epoche, die sie je gültig gesehen haben, und
> weisen danach jede niedrigere ab — auch mit gültiger Signatur.**

Sobald ein Gerät einmal einen Stand der Epoche 2 gesehen hat, ist der Schlüssel
der Epoche 1 für dieses Gerät tot. Die Grenze, ehrlich benannt: Ein Gerät,
dessen Netzverkehr ein Angreifer dauerhaft kontrolliert, bekommt den neueren
Stand nie zu sehen und bleibt beim alten Schlüssel. Dagegen hilft nur ein
Client-Update.

## Was die Signatur leistet — und was nicht

| Prüfung | Beantwortet | Deckt **nicht** ab |
|---|---|---|
| TLS | „Kommt die Datei von diesem Host?" | ob der Inhalt dort vom Herausgeber stammt |
| Ed25519 | „Hat die Pipeline des Herausgebers diese Bytes erzeugt?" | ob die Bytes inhaltlich stimmen |
| Quell-Extrakt + Deckung | „Wurde etwas erfunden oder weggelassen?“ | ob die Quelle recht hat |

Die Signatur beglaubigt auch eine Fehlklassifikation. Sie sagt, **wer** etwas
behauptet hat — nicht, dass es stimmt. Deshalb liegt der Quell-Extrakt bei: er
macht die Einordnung überhaupt erst überprüfbar.

Bewusst **nicht** mitveröffentlicht wird die vollständige Quellseite. Deren
Navigation, Fußzeile und Markup gehören nicht in eine Veröffentlichung, und die
Meldungstexte stehen ohnehin schon im Feed. Wer die Seite selbst abruft, prüft
sie gegen `sourceSha256`.

Ebenfalls ehrlich: Die Pipeline, die die Daten erzeugt, signiert sie auch. Wer
sie übernimmt, signiert mit. Die Signatur schützt gegen Manipulation beim
Hoster und gegen ein entwendetes Zugangs-Token — nicht gegen eine
kompromittierte Pipeline. Dagegen wirkt die öffentliche Historie: eine
Fälschung müsste dauerhaft stehen bleiben und wäre für jeden sichtbar, der
mitliest.

## Lizenz und Weiterverwendung

**Code und Schemata unter MIT** (`LICENSE`). **Für die Daten gilt `DATA.md`** —
und dort steht keine Datenlizenz, sondern der Grund dafür: Die Meldungen
stammen von der in `source` genannten fremden Seite, die keine Nutzungsbedingung
veröffentlicht. Lizenzieren kann nur, wem etwas gehört.

Wer die Daten nutzt: `source` und `generatedAt` mitführen, `validUntil`
beachten, den Datensatz nicht als offizielle Veröffentlichung ausgeben — und
diesen Spiegel verwenden, statt einen zweiten Abruf auf die Quelle zu bauen.
Das Ausführliche steht in `DATA.md`.

Sicherheitsbefunde: `SECURITY.md`.

## Rhythmus und Ausfallverhalten

Ein Lauf pro Tag. Läuft der Abruf ins Leere oder liefert der Parser nichts,
bricht die Pipeline ab und **lässt den letzten guten Stand stehen**, statt einen
leeren zu veröffentlichen. Ein Datensatz ohne Meldungen sieht aus wie „alles in
Ordnung" — das ist der gefährlichste mögliche Fehler dieses Feeds und deshalb an
beiden Enden abgesichert: hier beim Erzeugen, und im Client, der eine Kategorie
nicht von gefüllt auf leer fallen lässt.

Fehlt der Signaturschlüssel, veröffentlicht die Pipeline **nichts**. Unsigniert
ausliefern ist kein Rückfallpfad.
