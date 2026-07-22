# 🎂 Google Geburtstagsimporter

Ein Flask-Webinterface, um Geburtstage und andere datierte Ereignisse aus deinen Google-Kontakten automatisch in einen separaten Google Kalender ("Geburtstage") zu importieren – mit Web-GUI, Live-Statusanzeige und Dublettenprüfung.

## ✅ Features

- Liest Geburtstage **und alle anderen datierten Ereignisse** aus deinen Google Kontakten via People API
- Erstellt oder nutzt den Kalender „Geburtstage“
- Fügt nur **neue** Ereignisse ein (Vermeidung von Duplikaten)
- Leert den Kalender vor jeder Synchronisierung
- Webinterface mit Live-Statusanzeige (via Socket.IO)
- Aggregiertes Protokoll erscheint in Echtzeit direkt im Browser, ohne Kontaktdaten in Serverprotokolle zu schreiben
- Datensparsame Kontaktvorschau mit optionalem Filter und ohne Anzeige des Geburtsjahres
- Lokale OAuth2-Autorisierung via `credentials.json`
- Jede Browsersitzung verwendet eigene OAuth-Daten (keine gemeinsame Token-Datei)
- OAuth-Tokens werden nach 30 Tagen Inaktivität automatisch gelöscht
- Google-Zugriff und lokale OAuth-Daten können direkt in der Web-App widerrufen werden
- Kontakt- und Ereignisdaten werden nur im Arbeitsspeicher verarbeitet, nicht lokal exportiert

## 🚀 Installation

```bash
git clone https://github.com/dein-benutzername/geburtstagsimporter.git
cd geburtstagsimporter
pip install -r requirements.txt
```

Starte das Webinterface anschließend mit:

```bash
python3 app.py
```

Optional kann über die Umgebungsvariable `FLASK_SECRET_KEY` ein eigener
Session-Schlüssel gesetzt werden. Für den Betrieb ist ein solcher Schlüssel
Pflicht. Die Anwendung lädt außerdem eine lokale, nicht versionierte Datei
`.env`, falls der Schlüssel nicht bereits durch den Dienst gesetzt wurde.
Für lokale Tests ohne HTTPS kann `FLASK_SESSION_COOKIE_SECURE=0` gesetzt werden.
Die Einfügegeschwindigkeit kann über `EINFUEGE_PAUSE_SEKUNDEN` angepasst werden;
Standard sind `0.1` Sekunden pro Kalendereintrag. Bei Google-Rate-Limits nutzt
die Anwendung automatisch exponentiellen Backoff. Die Aufbewahrungsfrist für
OAuth-Tokens kann mit `OAUTH_TOKEN_AUFBEWAHRUNG_TAGE` angepasst werden; der
datenschutzfreundliche Standardwert beträgt 30 Tage seit der letzten Nutzung.

### Google API Einrichtung

Bevor du die Anwendung startest, musst du in der Google Cloud Console sowohl die **People API** als auch die **Calendar API** für dein Projekt aktivieren. Andernfalls endet der Zugriff auf deine Kontakte mit einem 403-Fehler.

Für den OAuth-Zustimmungsbildschirm werden nur diese Bereiche benötigt:

```text
https://www.googleapis.com/auth/contacts.readonly
https://www.googleapis.com/auth/calendar.app.created
https://www.googleapis.com/auth/calendar.calendarlist.readonly
```

Entferne dort alle anderen Bereiche wie `calendar`, `calendar.events`,
`calendar.acls`, `contacts`, `contacts.other.readonly`, BigQuery,
Cloud Platform oder Storage. Nach einer Änderung der Bereiche muss die
Google-Autorisierung im Browser neu durchgeführt werden.

Erstelle anschließend in der [Google Cloud Console](https://console.cloud.google.com/apis/credentials) einen OAuth2-Client vom Typ **Webanwendung** und lade die Datei `credentials.json` herunter. Diese Datei muss sich im selben Verzeichnis wie `app.py` befinden. Gib dem Client einen klaren Namen (z. B. „Geburtstagsimporter Web-App“) und hinterlege die autorisierten Redirect-URIs für deine Web-App. Die Einträge müssen **exakt** mit Schema, Host und Port übereinstimmen (inklusive `/oauth2callback`). Gehe dabei wie folgt vor:

1. In der Google Cloud Console → **APIs & Dienste** → **Anmeldedaten** → OAuth‑Client (**Webanwendung**) öffnen.
2. Unter „Autorisierte Redirect‑URIs“ die **exakt** verwendete URL eintragen (inkl. Schema, Host, Port und `/oauth2callback`).
3. Typische Beispiele:

   * `http://localhost:8022/oauth2callback`
   * `http://<SERVER-IP>:8022/oauth2callback`
   * `https://geburtstage.example.de/oauth2callback`
4. Änderungen speichern und erneut den OAuth‑Flow starten.

Die Anwendung ist dann unter `http://<SERVER-IP>:8022` erreichbar.

Wenn du hinter einem Reverse-Proxy arbeitest, setze `PREFERRED_URL_SCHEME=https` und stelle sicher, dass der Proxy die `X-Forwarded-*`-Header korrekt weitergibt. Optional kannst du die erwartete Callback-URL über `OAUTH_REDIRECT_URI` überschreiben, z. B. `https://geburtstage.example.de/oauth2callback`. Diese URL muss ebenfalls in der Google Cloud Console als autorisierte Redirect-URI eingetragen sein.

Beim ersten Start wirst du auf der Webseite nach der Google-Autorisierung
gefragt. Klicke auf den angezeigten Link, erteile den Zugriff und kehre danach
automatisch zur Web-App zurück.

Über **Vorschau laden** kannst du vorab prüfen, welche datierten Kontaktfelder die
People API mit `contacts.readonly` liefert. Die Vorschau zeigt höchstens acht Treffer
und blendet vorhandene Jahresangaben aus. Klicke anschließend im Browser auf
**Jetzt synchronisieren**. Aggregierte Statusmeldungen erscheinen live im Bereich
„Live-Protokoll“. Namen, Geburtstage und andere datierte Kontaktfelder werden nur
für den laufenden Vorgang im Arbeitsspeicher gehalten.

Mit **Google-Verbindung trennen** wird der verwendete OAuth-Token bei Google
widerrufen und die serverseitige Token-Datei unmittelbar gelöscht. Die vollständige
Beschreibung von Datenzugriff, Weitergabe, Schutz, Aufbewahrung und Löschung steht
unter [calendar.do1ffe.de/datenschutz](https://calendar.do1ffe.de/datenschutz).

## OAuth-Verifizierungsdemo

Die überarbeitete Demonstration für die Google-Prüfung ist öffentlich unter
[oauth-verification-demo-2026-v2.mp4](https://calendar.do1ffe.de/static/oauth-verification-demo-2026-v2.mp4)
abrufbar. Sie zeigt den OAuth-Ablauf, die sichtbare People-API-Kontaktvorschau für
`contacts.readonly`, die beiden Calendar-Bereiche und die Datenschutzmaßnahmen.
