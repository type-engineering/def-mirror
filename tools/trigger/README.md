# Auslöser für den Tageslauf

GitHubs `schedule` startet regelmäßig 4–5 Stunden zu spät. 
Pünktlich ist nur `workflow_dispatch` — also wird der Lauf von
außen angestoßen, und zwar von zwei voneinander unabhängigen Stellen. Die
Tagessperre in `mirror.yml` stellt sicher dass nur ein Stand pro Tag 
erfasst wird.

| Auslöser | Zeit (UTC) | Rolle |
|---|---|---|
| cron-job.org | 05:07 | extern, Hauptauslöser |
| Cloudflare Worker (`worker.js`) | 05:15 | extern, unabhängige Redundanz |
| GitHub `schedule` | 05:23, 06:53, 09:23 | Netz darunter, meist verspätet |
| healthchecks.io | Frist 06:00 | Alarm, wenn bis dahin kein Stand vorliegt |

Alle drei Schritte unten sind außerhalb des Repos eingerichtet.

## Personal Access Token für die externen Trigger

Zwei "fine-grained" Personal Access Token (PAT) sind eingerichtet — 
ein widerrufener Token führt nicht zum Ausfall beider externer Trigger.

- *Resource owner*: `type-engineering`
- *Repository access*: `def-mirror`
- *Permissions*: **Actions: Read and write** 
- Ablaufdatum festhalten. Ein abgelaufener PAT ist der wahrscheinlichste Grund,
  warum ein Auslöser still wegfällt.

Achtung: sobald ein PAC eingetragen wird löst dies einen echten Lauf aus; 
(die Tagessperre beendet ihn, wenn bereits ein Stand vorliegt):

```bash
curl -i -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $PAT" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  https://api.github.com/repos/type-engineering/def-mirror/actions/workflows/mirror.yml/dispatches \
  -d '{"ref":"main"}'
```

Erwartet: `HTTP/2 204`. Alles andere ist ein Fehler.

## 1 · cron-job.org

In der Lauf-Historie des Workflows schlägt cron-job.org aktuell häufig fehl. 
Typische Ursachen:

| Symptom im Verlauf | Ursache |
|---|---|
| keine Ausführungen | Job fehlt, ist deaktiviert oder wurde nach Fehlern automatisch abgeschaltet |
| 404 | falscher Pfad, oder der PAT sieht das Repo nicht |
| 401 | PAT abgelaufen oder `Bearer ` fehlt |
| 403 | PAT ohne *Actions: write*, oder `User-Agent` fehlt |
| 422 | Body fehlt oder `ref` falsch |
| Ausführung zur falschen Zeit | Zeitzone des Jobs steht auf Europe/Berlin statt UTC |

Sollte als auch nach Fix der Probleme ein solches Symptom vorliegen, kann die obenstehende
Tabelle bei der Fehlersuche unterstützen.

Soll-Einstellungen:

- URL: `https://api.github.com/repos/type-engineering/def-mirror/actions/workflows/mirror.yml/dispatches`
- Zeitplan: täglich 05:07, **Zeitzone UTC**
- *Advanced* → Request method: **POST**
- Headers:
  - `Accept: application/vnd.github+json`
  - `Authorization: Bearer <PAT>`
  - `X-GitHub-Api-Version: 2022-11-28`
  - `Content-Type: application/json`
  - `User-Agent: def-mirror-trigger`
- Request body: `{"ref":"main"}`
- *Notifications*: bei Fehlschlag und bei automatischer Deaktivierung
  benachrichtigen
- „Test run“ ausführen, Ergebnis muss 204 sein

## 2 Cloudflare Worker

Zur Einrichtung des Konto aus diesem Verzeichnis die folgenden Schrtte ausführen:

```bash
cd tools/trigger
npx wrangler login
npx wrangler secret put GITHUB_TOKEN   # zweiten PAT einfügen
npx wrangler deploy
```

Danach im Cloudflare-Dashboard unter *Workers → def-mirror-trigger →
Settings → Triggers* prüfen, dass der Cron `15 5 * * *` eingetragen ist.
Die Ausführungen und ihre Fehler stehen unter *Logs*.

Für den manuellen Start eines Tests:

```bash
npx wrangler dev --test-scheduled
# in zweitem Terminal:
curl "http://localhost:8787/__scheduled?cron=15+5+*+*+*"
```

Das löst über die API gezielt einen Lauf aus.

## 3 · healthchecks.io

Dient der Notifikation bei fehlenden oder fehgelschlagenen Läufen.

Umstellen auf einen Zeitplan:

- Check öffnen → *Schedule* → **Cron**
- Cron-Ausdruck: `15 5 * * *`
- Time zone: **UTC**
- Grace time: **45 Minuten**

Damit kommt der Alarm um 06:00 UTC (08:00 MESZ, 07:00 MEZ), wenn bis dahin
kein „ok“ eingetroffen ist. Spätere „ok“ der GitHub-Termine stören nicht; ein
`/fail` aus einem späteren Lauf löst allerdings ebenfalls einen Alarm aus —
das ist gewollt.

Benachrichtigungskanal (E-Mail o. ä.) unter *Integrations* prüfen, sonst
alarmiert der Check ins Leere.