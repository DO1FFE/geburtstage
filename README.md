# 🎂 Google Geburtstagsimporter

Ein Flask-Webinterface, um Geburtstage und andere datierte Ereignisse aus deinen Google-Kontakten automatisch in einen separaten Google Kalender ("Geburtstage") zu importieren – mit Web-GUI, Live-Statusanzeige und Dublettenprüfung.

## ✅ Features

- Liest Geburtstage **und alle anderen datierten Ereignisse** aus deinen Google Kontakten via People API
- Erstellt oder nutzt den Kalender „Geburtstage“
- Fügt nur **neue** Ereignisse ein (Vermeidung von Duplikaten)
- Leert den Kalender vor jeder Synchronisierung
- Webinterface mit Live-Statusanzeige (via Socket.IO)
- Log erscheint in Echtzeit direkt im Browser
- Beim Hinzufügen steht im Log genau, welches Ereignis an welchem Datum für welche Person eingetragen wurde
- Lokale OAuth2-Autorisierung via `credentials.json`
- Jede Browsersitzung verwendet eigene OAuth-Daten (keine gemeinsame Token-Datei)

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
Session-Schlüssel gesetzt werden.

### Google API Einrichtung

Bevor du die Anwendung startest, musst du in der Google Cloud Console sowohl die **People API** als auch die **Calendar API** für dein Projekt aktivieren. Andernfalls endet der Zugriff auf deine Kontakte mit einem 403-Fehler.

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

Klicke anschließend im Browser auf **Jetzt synchronisieren**. Alle Statusmeldungen
– inklusive der erfolgreich übertragenen Ereignisse – erscheinen live im Bereich
"Log" auf der Webseite. Bei jeder Synchronisierung wird außerdem automatisch eine
Datei `Geburtstage.txt` erzeugt, die alle gefundenen Ereignisse nach Datum sortiert enthält.
