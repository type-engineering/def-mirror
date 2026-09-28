// Zweiter, unabhängiger Auslöser für mirror.yml — neben cron-job.org.
//
// GitHubs `schedule` startet hier regelmäßig Stunden zu spät; auf
// `workflow_dispatch` reagiert GitHub dagegen sofort. Dieser Worker ruft
// deshalb zu einer festen Zeit die Dispatch-API auf. Doppelte Auslösungen sind
// harmlos: die Tagessperre im Workflow beendet jeden weiteren Lauf des Tages.
//
// Der Worker erntet nicht und signiert nicht — der Schlüssel bleibt in GitHub.
// Er hat keinen fetch-Handler, ist also von außen nicht aufrufbar.

const VERSUCHE = 3;

export default {
  async scheduled(controller, env, ctx) {
    const url =
      `https://api.github.com/repos/${env.REPO}/actions/workflows/` +
      `${env.WORKFLOW}/dispatches`;

    let letzterFehler = "";
    for (let versuch = 1; versuch <= VERSUCHE; versuch++) {
      try {
        const antwort = await fetch(url, {
          method: "POST",
          headers: {
            "Accept": "application/vnd.github+json",
            "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            // GitHub lehnt Anfragen ohne User-Agent ab.
            "User-Agent": "def-mirror-trigger",
          },
          body: JSON.stringify({ ref: env.REF }),
        });
        // 204 heißt: Lauf angenommen. 401/403/404 wird ein Wiederholen nicht
        // heilen (PAT abgelaufen, falsche Rechte, falscher Pfad).
        if (antwort.status === 204) {
          console.log(`Dispatch angenommen (Versuch ${versuch}).`);
          return;
        }
        letzterFehler = `HTTP ${antwort.status}: ${await antwort.text()}`;
        if (antwort.status < 500 && antwort.status !== 429) break;
      } catch (e) {
        letzterFehler = String(e);
      }
      await new Promise((r) => setTimeout(r, 10_000 * versuch));
    }
    // Werfen statt still enden: so erscheint der Lauf in den Cloudflare-Logs
    // als fehlgeschlagen. Alarmiert wird trotzdem über healthchecks.io, weil
    // dann das "ok" ausbleibt.
    throw new Error(`Dispatch gescheitert: ${letzterFehler}`);
  },
};
