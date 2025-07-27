# 🎂 Google Geburtstagsimporter

Ein Flask-Webinterface, um Geburtstage aus deinen Google-Kontakten automatisch in einen separaten Google Kalender ("Geburtstage") zu importieren – mit Web-GUI, Live-Statusanzeige und Dublettenprüfung.

## ✅ Features

- Liest Geburtstage aus deinen Google Kontakten via People API
- Erstellt oder nutzt den Kalender „Geburtstage“
- Fügt nur **neue** Geburtstage ein (Vermeidung von Duplikaten)
- Webinterface mit Live-Statusanzeige (via Socket.IO)
- Logging in `log.txt` mit Zeitstempeln
- Lokale OAuth2-Autorisierung via `credentials.json`

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

### Google API Einrichtung

Erstelle in der [Google Cloud Console](https://console.cloud.google.com/apis/credentials) einen OAuth2-Client vom Typ **Desktop-App** und lade die Datei `credentials.json` herunter. Diese Datei muss sich im selben Verzeichnis wie `app.py` befinden. Achte darauf, dass in den heruntergeladenen Daten die Standard-Redirect-URIs (`urn:ietf:wg:oauth:2.0:oob` und `http://localhost`) enthalten sind, damit die Anmeldung korrekt funktioniert.

Die Anwendung ist dann unter `http://<SERVER-IP>:8022` erreichbar.

Beim ersten Start wirst du auf der Webseite nach der Google-Autorisierung
gefragt. Klicke auf den angezeigten Link, erteile den Zugriff und kopiere den
Anmeldecode in das bereitgestellte Feld.
