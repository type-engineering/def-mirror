# def-mirror

Ein täglich gespiegelter, **signierter** Statusdatensatz: 
Meldungen über sicherheitsrelevante Hinweise und Wegsperrungen sowie von Defekten einer öffentlichen Quellseite, 
maschinell in ein stabiles JSON-Schema überführt und hier geteilt.

Zweck des Repositorys ist nicht die Auslieferung, sondern die
**Nachvollziehbarkeit**: Jeder ausgelieferte Stand liegt als datierter Commit
vor, zusammen mit der Signatur und einem Extrakt der Quellzeilen, aus denen er
entstanden ist.

## Artefakte

| Datei | Inhalt |
|---|---|
| `defects.json` | Nutzdaten |
| `defects.signed.json` | dieselben Bytes in einem signierten Umschlag |
| `defects-source.txt` | Quell-Extrakt: extrahierte Zeilen vor der Einordnung |
| `KEYS` | öffentliche Schlüssel (Vertrauensanker) |
| `tools/` | Prüfwerkzeug und Schemata |

## Prüfen

```bash
python3 -m venv .venv && .venv/bin/pip install -r tools/requirements.txt
.venv/bin/python tools/verify.py --envelope defects.signed.json --keys KEYS \
    --expect-json defects.json --source defects-source.txt
```

Geprüft wird in den folgenden Stufen:

1. **Umschlag** Form, Verfahren und Version wie erwartet.
2. **Signatur** gültig unter dem Schlüssel zur genannten `keyId`. Eine
   unbekannte `keyId` ist ein Fehler
3. **Schema**: Nutzdaten entsprechen `tools/defects.schema.json`.
4. **Frische**: `validUntil` noch nicht verstrichen?
5. **Byte-Gleichheit**: die lesbare `defects.json` ist Byte für Byte das, was
   signiert wurde.
6. **Herkunft**: `extractSha256` passt zum mitveröffentlichten Quell-Extrakt.
7. **Deckung**: jeder Text im Feed steht so auch im Extrakt. Meldung bei Abweichung.

Exit 0 heißt: alle Stufen bestanden.

Ohne Argumente prüft das Werkzeug, was es kann; `--expect-json` und
`--source` sind optional. Ein Abruf direkt gegen die ausgelieferte URL ist ebenfalls möglich:

```bash
.venv/bin/python tools/verify.py --url <URL>/defects.signed.json --keys KEYS
```

## Schema — `defects.json`

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

### Kopf (Head)

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
| `id` | 12 Hex | Stabile, **inhaltsabgeleitete** Kennung: derselbe Eintrag hat morgen dieselbe `id`, unabhängig von seiner Position in der Liste. Normalisiert über NFKC und Weißraum, damit ein Reformat der Quelle einen bekannten Eintrag nicht als „neu" ausgibt. |
| `severity` | `info` \| `warning` \| `critical` | **Rein kategoriebasiert**: `closures` → `critical`, `defects` → `warning`, `notices` → `info`. |
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

Ed25519, ein aktiver Schlüssel und eine Reserve (keyEpoch). Kein CA, kein
Widerrufsserver, keine Ablaufdaten. Die privaten Schlüssel entstehen von Hand
und offline; sie liegen in keinem Repository und in keiner Cloud.

> **Clients merken sich die höchste Epoche, die sie je gültig gesehen haben, und
> weisen danach jede niedrigere ab — auch bei gültiger Signatur.**

Sobald ein Client einmal einen Stand der Epoche 2 gesehen hat, ist der Schlüssel
der Epoche 1 für diesen Client tot. Sollte der ein Angreifer den Netzverkehr eines Clients
*dauerhaft kontrollieren*, bekommt dieser den neueren Stand ggf. nie zu sehen und bliebe beim 
alten Schlüssel. Dagegen hilft dann nur ein Client-Update.

## Was die Signatur leistet — und was nicht

| Prüfung | Beantwortet | Deckt **nicht** ab |
|---|---|---|
| TLS | „Kommt die Datei von diesem Host?" | ob der Inhalt dort vom Herausgeber stammt |
| Ed25519 | „Hat die Pipeline des Herausgebers diese Bytes erzeugt?" | ob die Bytes inhaltlich stimmen |
| Quell-Extrakt + Deckung | „Wurde etwas erfunden oder weggelassen?“ | ob die Quelle recht hat |

Die Signatur beglaubigt auch eine Fehlklassifikation. Deshalb liegt der Quell-Extrakt bei: 
er macht die Einordnung überprüfbar.

Bewusst **nicht** mitveröffentlicht wird die vollständige Quellseite. 
Wer die Seite selbst abruft, prüft sie gegen `sourceSha256`.

Die Pipeline, die die Daten erzeugt, signiert sie auch. Wer sie übernimmt, signiert mit. 
Die Signatur schützt gegen Manipulation beim Hoster und gegen ein entwendetes Zugangs-Token — 
nicht gegen eine kompromittierte Pipeline. Dagegen wirkt die öffentliche Historie: eine
Fälschung müsste dauerhaft stehen bleiben und wäre für jeden sichtbar, der
mitliest.

## Lizenz und Weiterverwendung

**Code und Schemata unter MIT** (`LICENSE`). **Für die Daten gilt `DATA.md`** —
Die Meldungen stammen von der in `source` genannten fremden Seite, die keine Nutzungsbedingung
veröffentlicht.

Dieser Mirror dient dazu, die Source Website vor einer hohen Anzahl an Anfragen zu schützen,
und die abgeleiteten sicherheitsrelevanten Informationen in einem historisch nachvollziehbaren
Format bereitzustellen.

Zum Thema Sicherheitsbefunde bitte in `SECURITY.md` nachsehen.

## Rhythmus und Ausfallverhalten

Ein Lauf pro Tag. Läuft der Abruf ins Leere oder liefert der Parser nichts,
bricht die Pipeline ab und **lässt den letzten guten Stand stehen**, statt einen
leeren zu veröffentlichen. 

Fehlt der Signaturschlüssel, veröffentlicht die Pipeline **nichts**.
