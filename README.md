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

Die Anwendung ist dann unter `http://<SERVER-IP>:8022` erreichbar.
