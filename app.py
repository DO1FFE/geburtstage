import eventlet
eventlet.monkey_patch()

import os
import datetime
import json
import random
import signal
import secrets
import sys
from contextvars import ContextVar
from zoneinfo import ZoneInfo

from flask import Flask, render_template, jsonify, request, session, url_for, redirect, has_request_context
from flask_socketio import SocketIO, join_room
from google.auth.transport.requests import Request as GoogleAuthRequest
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from werkzeug.middleware.proxy_fix import ProxyFix
import time

SCOPES = [
    'https://www.googleapis.com/auth/contacts.readonly',
    'https://www.googleapis.com/auth/calendar.app.created',
    'https://www.googleapis.com/auth/calendar.calendarlist.readonly'
]
ERLAUBTE_OAUTH_BEREICHE = set(SCOPES)

# Print all messages to console when True. When False only important
# messages are shown.
VERBOSE_CONSOLE = False
PROJEKT_DIR = os.path.dirname(os.path.abspath(__file__))
ANZEIGE_ZEITZONE = ZoneInfo('Europe/Berlin')


def umgebung_ist_wahr(name, standard=False):
    """Liest boolesche Einstellungen aus Umgebungsvariablen."""
    wert = os.environ.get(name)
    if wert is None:
        return standard
    return wert.lower() in ('1', 'true', 'yes', 'ja', 'on')


def umgebung_als_float(name, standard):
    """Liest eine Fließkommazahl aus der Umgebung."""
    wert = os.environ.get(name)
    if wert is None:
        return standard
    return float(wert)


def umgebung_als_int(name, standard):
    """Liest eine Ganzzahl aus der Umgebung."""
    wert = os.environ.get(name)
    if wert is None:
        return standard
    return int(wert)


def lade_env_datei(pfad=None):
    """Lädt lokale Umgebungswerte aus .env, ohne bestehende Werte zu überschreiben."""
    env_pfad = pfad or os.path.join(PROJEKT_DIR, '.env')
    if not os.path.exists(env_pfad):
        return

    with open(env_pfad, 'r', encoding='utf-8') as datei:
        for zeile in datei:
            zeile = zeile.strip()
            if not zeile or zeile.startswith('#') or '=' not in zeile:
                continue
            name, wert = zeile.split('=', 1)
            name = name.strip()
            wert = wert.strip().strip('"').strip("'")
            if name and name not in os.environ:
                os.environ[name] = wert


def lade_flask_secret_key():
    """Erzwingt einen eigenen geheimen Schlüssel für produktive Sessions."""
    secret_key = os.environ.get('FLASK_SECRET_KEY')
    if not secret_key:
        raise RuntimeError(
            "FLASK_SECRET_KEY muss gesetzt sein, damit Sessions auf calendar.do1ffe.de sicher signiert werden."
        )
    return secret_key


def aktueller_zeitstempel():
    """Liefert den aktuellen Status-Zeitstempel in deutscher Ortszeit."""
    return datetime.datetime.now(ANZEIGE_ZEITZONE).strftime('%Y-%m-%d %H:%M:%S %Z (Europe/Berlin)')


lade_env_datei()

app = Flask(__name__)
app.secret_key = lade_flask_secret_key()
app.config.update(
    PREFERRED_URL_SCHEME=os.environ.get('PREFERRED_URL_SCHEME', 'https'),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=umgebung_ist_wahr('FLASK_SESSION_COOKIE_SECURE', True),
)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)
socketio = SocketIO(app, async_mode='eventlet', manage_session=False)
TOKEN_SPEICHER_DIR = os.environ.get(
    'TOKEN_SPEICHER_DIR',
    os.path.join(app.instance_path, 'oauth_tokens')
)
CREDENTIALS_DATEI = os.environ.get(
    'GOOGLE_CREDENTIALS_FILE',
    os.path.join(PROJEKT_DIR, 'credentials.json')
)
EINFÜGE_PAUSE_SEKUNDEN = umgebung_als_float('EINFUEGE_PAUSE_SEKUNDEN', 0.1)
RATE_LIMIT_START_WARTEZEIT = umgebung_als_float('RATE_LIMIT_START_WARTEZEIT', 1.0)
RATE_LIMIT_MAX_WARTEZEIT = umgebung_als_float('RATE_LIMIT_MAX_WARTEZEIT', 32.0)
RATE_LIMIT_MAX_VERSUCHE = umgebung_als_int('RATE_LIMIT_MAX_VERSUCHE', 6)
AKTIVE_STATUS_SITZUNG = ContextVar('aktive_status_sitzung', default=None)
laufende_synchronisationen = set()
synchronisations_sperre = eventlet.semaphore.Semaphore()


def emit_status(msg, sitzungs_id=None):
    """Sendet eine Statusmeldung an die passende Web-Sitzung."""
    timestamp = aktueller_zeitstempel()
    line = f"{timestamp} - {msg}"
    ziel_sitzung = sitzungs_id or AKTIVE_STATUS_SITZUNG.get()
    if ziel_sitzung is None and has_request_context():
        ziel_sitzung = session.get('sitzungs_id')

    if ziel_sitzung:
        socketio.emit('status', line, to=ziel_sitzung)
    else:
        socketio.emit('status', line)

    important = any(x in msg for x in ('⚠️', '❌', '🎉', 'Server'))
    if VERBOSE_CONSOLE or important:
        print(line, flush=True)


def ist_rate_limit_fehler(fehler):
    """Erkennt Google-Quota- und Rate-Limit-Fehler."""
    status = getattr(getattr(fehler, 'resp', None), 'status', None)
    fehlertext = str(fehler).lower()
    rate_limit_gründe = (
        'ratelimitexceeded',
        'rate limit',
        'userratelimitexceeded',
        'quotaexceeded',
        'quota exceeded',
    )
    return status in (403, 429) and any(grund in fehlertext for grund in rate_limit_gründe)


def google_fehler_status(fehler):
    """Liefert den HTTP-Status eines Google-API-Fehlers."""
    return getattr(getattr(fehler, 'resp', None), 'status', None)


def ist_wiederholbarer_google_fehler(fehler):
    """Erkennt kurzzeitige Google-API-Fehler, die einen neuen Versuch lohnen."""
    status = google_fehler_status(fehler)
    return status in (429, 500, 502, 503, 504) or ist_rate_limit_fehler(fehler)


def warte_wegen_google_api_fehler(versuch, aktion, fehler):
    """Wartet mit exponentiellem Backoff und etwas Jitter auf einen neuen Versuch."""
    if not ist_wiederholbarer_google_fehler(fehler):
        return False

    if versuch >= RATE_LIMIT_MAX_VERSUCHE:
        return False

    basis_wartezeit = min(
        RATE_LIMIT_MAX_WARTEZEIT,
        RATE_LIMIT_START_WARTEZEIT * (2 ** versuch)
    )
    jitter = random.uniform(0, min(1.0, basis_wartezeit * 0.25))
    wartezeit = basis_wartezeit + jitter
    status = google_fehler_status(fehler)
    grund = 'Rate Limit' if ist_rate_limit_fehler(fehler) else f'HTTP {status}'
    emit_status(f"⏳ Google API Fehler beim {aktion} ({grund}). Neuer Versuch in {wartezeit:.1f} Sekunden...")
    time.sleep(wartezeit)
    return True


def führe_google_api_aus(anforderung, aktion):
    """Führt eine Google-API-Anforderung mit Wiederholungen bei kurzzeitigen Fehlern aus."""
    versuch = 0
    while True:
        try:
            return anforderung.execute()
        except HttpError as fehler:
            if warte_wegen_google_api_fehler(versuch, aktion, fehler):
                versuch += 1
                continue
            raise


def handle_sigint(sig, frame):
    """Gracefully stop the server when CTRL-C is pressed."""
    emit_status("Server wird beendet...")
    socketio.stop()
    sys.exit(0)

signal.signal(signal.SIGINT, handle_sigint)

flows = {}


def aktuelle_sitzungs_id():
    """Erzeugt oder liefert die harmlose Sitzungs-ID für Cookie und Socket-Raum."""
    sitzungs_id = session.get('sitzungs_id')
    if not sitzungs_id:
        sitzungs_id = secrets.token_urlsafe(32)
        session['sitzungs_id'] = sitzungs_id
    return sitzungs_id


def hole_csrf_token():
    """Erzeugt oder liefert das CSRF-Token der aktuellen Sitzung."""
    csrf_token = session.get('csrf_token')
    if not csrf_token:
        csrf_token = secrets.token_urlsafe(32)
        session['csrf_token'] = csrf_token
    return csrf_token


def csrf_token_ist_gueltig():
    """Prüft das CSRF-Token aus dem Sync-Request."""
    erwartetes_token = session.get('csrf_token', '')
    gesendetes_token = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token', '')
    return secrets.compare_digest(gesendetes_token, erwartetes_token)


def starte_synchronisation_für_sitzung(sitzungs_id):
    """Merkt, dass für diese Browser-Sitzung bereits ein Lauf aktiv ist."""
    with synchronisations_sperre:
        if sitzungs_id in laufende_synchronisationen:
            return False
        laufende_synchronisationen.add(sitzungs_id)
        return True


def beende_synchronisation_für_sitzung(sitzungs_id):
    """Gibt den Synchronisationsstart für diese Browser-Sitzung wieder frei."""
    with synchronisations_sperre:
        laufende_synchronisationen.discard(sitzungs_id)


def sicherer_dateiname(wert):
    """Reduziert einen Sitzungswert auf sichere Dateinamen-Zeichen."""
    return ''.join(zeichen for zeichen in wert if zeichen.isalnum() or zeichen in ('-', '_'))


def token_pfad():
    sitzungs_id = sicherer_dateiname(aktuelle_sitzungs_id())
    return os.path.join(TOKEN_SPEICHER_DIR, f"{sitzungs_id}.json")


def zugangsdaten_als_json(creds):
    """Serialisiert Google-Zugangsdaten versionsübergreifend für den Token-Speicher."""
    if hasattr(creds, 'to_json'):
        return creds.to_json()

    zugangsdaten = {
        'token': creds.token,
        'refresh_token': creds.refresh_token,
        'token_uri': creds.token_uri,
        'client_id': creds.client_id,
        'client_secret': creds.client_secret,
        'scopes': creds.scopes,
    }
    return json.dumps(zugangsdaten)


def normalisiere_oauth_bereiche(wert):
    """Liest OAuth-Bereiche aus gespeicherten Token-Daten als Menge."""
    if not wert:
        return set()
    if isinstance(wert, str):
        return set(wert.split())
    if isinstance(wert, (list, tuple, set)):
        return set(wert)
    return set()


def speichere_zugangsdaten(creds):
    """Speichert OAuth-Zugangsdaten serverseitig statt im Browser-Cookie."""
    os.makedirs(TOKEN_SPEICHER_DIR, mode=0o700, exist_ok=True)
    os.chmod(TOKEN_SPEICHER_DIR, 0o700)
    pfad = token_pfad()
    temporaerer_pfad = f"{pfad}.tmp"
    with open(temporaerer_pfad, 'w', encoding='utf-8') as datei:
        datei.write(zugangsdaten_als_json(creds))
    os.chmod(temporaerer_pfad, 0o600)
    os.replace(temporaerer_pfad, pfad)


def lösche_zugangsdaten():
    """Entfernt beschädigte oder abgelaufene serverseitige OAuth-Daten."""
    try:
        os.remove(token_pfad())
    except FileNotFoundError:
        pass


def lade_zugangsdaten():
    """Lädt OAuth-Zugangsdaten aus dem serverseitigen Token-Speicher."""
    session.pop('creds', None)
    pfad = token_pfad()
    if not os.path.exists(pfad):
        return None

    try:
        with open(pfad, 'r', encoding='utf-8') as datei:
            daten = json.load(datei)
        gespeicherte_bereiche = normalisiere_oauth_bereiche(
            daten.get('scopes') or daten.get('scope')
        )
        if gespeicherte_bereiche and gespeicherte_bereiche != ERLAUBTE_OAUTH_BEREICHE:
            emit_status(
                "⚠️ Gespeicherte OAuth-Zugangsdaten passen nicht zu den aktuellen "
                "Berechtigungen. Bitte erneut über Google anmelden."
            )
            lösche_zugangsdaten()
            return None
        return Credentials.from_authorized_user_info(daten, SCOPES)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        emit_status(f"⚠️ Gespeicherte OAuth-Zugangsdaten konnten nicht gelesen werden: {exc}")
        lösche_zugangsdaten()
        return None


@app.before_request
def bereite_sitzung_vor():
    """Stellt Sitzungs-ID und CSRF-Token bereit, ohne OAuth-Daten ins Cookie zu legen."""
    aktuelle_sitzungs_id()
    hole_csrf_token()
    session.pop('creds', None)


@socketio.on('connect')
def websocket_verbinden():
    """Verbindet den Browser mit seinem privaten Status-Raum."""
    sitzungs_id = session.get('sitzungs_id')
    if sitzungs_id:
        join_room(sitzungs_id)


def get_redirect_uri():
    """Ermittelt die Redirect-URL dynamisch oder nutzt eine gesetzte Vorgabe."""
    redirect_override = os.environ.get('OAUTH_REDIRECT_URI')
    if redirect_override:
        emit_status(f"OAuth-Redirect-URI (Umgebung): {redirect_override}")
        return redirect_override
    uri = url_for("oauth2callback", _external=True)
    emit_status(f"OAuth-Redirect-URI (berechnet): {uri}")
    return uri


def get_services():
    creds = lade_zugangsdaten()

    if creds and not creds.valid and creds.refresh_token:
        try:
            creds.refresh(GoogleAuthRequest())
            speichere_zugangsdaten(creds)
        except Exception as exc:
            emit_status(f"⚠️ OAuth-Zugangsdaten konnten nicht erneuert werden: {exc}")
            lösche_zugangsdaten()
            creds = None

    if not creds or not creds.valid:
        emit_status("Authentifiziere Benutzer über Google...")
        flow = Flow.from_client_secrets_file(CREDENTIALS_DATEI, scopes=SCOPES)
        flow.redirect_uri = get_redirect_uri()
        auth_url, state = flow.authorization_url(prompt='consent')
        flows[state] = flow
        session['oauth_state'] = state
        return None, None, auth_url

    people_service = build('people', 'v1', credentials=creds)
    calendar_service = build('calendar', 'v3', credentials=creds)
    return people_service, calendar_service, None

def get_or_create_calendar(service, name="Geburtstage"):
    emit_status(f"Suche nach Kalender '{name}'...")
    calendars = führe_google_api_aus(
        service.calendarList().list(),
        'Abrufen der Kalenderliste'
    )
    for cal in calendars.get('items', []):
        if cal['summary'].lower() == name.lower():
            emit_status("Kalender bereits vorhanden.")
            return cal['id']

    emit_status("Kalender nicht gefunden – wird erstellt.")
    new_cal = {'summary': name, 'timeZone': 'Europe/Berlin'}
    created = führe_google_api_aus(
        service.calendars().insert(body=new_cal),
        'Erstellen des Kalenders'
    )
    return created['id']

def clear_calendar(service, calendar_id):
    """Remove all events from the given calendar."""
    emit_status("Lösche vorhandene Einträge im Kalender...")
    page_token = None
    deleted_any = False
    while True:
        try:
            events = führe_google_api_aus(
                service.events().list(
                    calendarId=calendar_id,
                    pageToken=page_token,
                    maxResults=2500,
                ),
                'Abrufen der Kalenderereignisse'
            )
        except HttpError as e:
            emit_status(f"❌ Fehler beim Abrufen der Kalenderereignisse: {e}")
            raise

        for ev in events.get('items', []):
            while True:
                try:
                    führe_google_api_aus(
                        service.events().delete(calendarId=calendar_id, eventId=ev['id']),
                        f"Löschen des Ereignisses '{ev.get('summary', '')}'"
                    )
                    deleted_any = True
                    time.sleep(0.1)
                    break
                except HttpError as e:
                    emit_status(f"❌ Fehler beim Löschen des Ereignisses '{ev.get('summary', '')}': {e}")
                    break

        page_token = events.get('nextPageToken')
        if not page_token:
            break

    if deleted_any:
        emit_status("Kalender geleert.")
    else:
        emit_status("Kalender war bereits leer.")

def get_all_events(people_service):
    """Fetch birthdays and all dated events from Google contacts."""
    emit_status("Lese Kontakte und Ereignisse...")
    events = []
    page_token = None
    while True:
        results = führe_google_api_aus(
            people_service.people().connections().list(
                resourceName='people/me',
                personFields='names,birthdays,events',
                pageSize=1000,
                pageToken=page_token
            ),
            'Abrufen der Kontakte'
        )

        for person in results.get('connections', []):
            names = person.get('names', [])
            if not names:
                continue
            name = names[0].get('displayName')

            for b in person.get('birthdays', []):
                date = b.get('date')
                if date and date.get('month') and date.get('day'):
                    events.append({
                        'name': name,
                        'date': date,
                        'event_type': 'birthday',
                        'label': 'Geburtstag'
                    })

            for e in person.get('events', []):
                typ = (e.get('type') or '').lower()
                if typ == 'birthday':
                    # already handled above
                    continue
                date = e.get('date')
                if not date or not date.get('month') or not date.get('day'):
                    continue
                label = e.get('formattedType') or e.get('customType') or typ
                events.append({
                    'name': name,
                    'date': date,
                    'event_type': typ or 'event',
                    'label': label
                })

        page_token = results.get('nextPageToken')
        if not page_token:
            break

    return events

def write_events_file(events, filename="Geburtstage.txt"):
    """Write sorted events to a text file."""
    events = sorted(
        events,
        key=lambda b: (b['date']['month'], b['date']['day'], b['date'].get('year', 0))
    )

    with open(filename, 'w') as f:
        for ev in events:
            d = ev['date']
            year = d.get('year', 2000)
            dt = datetime.date(year, d['month'], d['day'])
            line = f"{dt.strftime('%d.%m.%Y')} {ev['name']}"
            label = ev.get('label')
            if label:
                line += f" ({label})"
            f.write(line + "\n")
    emit_status(f"✏️ {filename} geschrieben")

def create_events(calendar_service, calendar_id, events):
    emit_status("Prüfe vorhandene Ereignisse im Kalender...")
    existing = set()
    page_token = None
    created_count = 0
    skipped_count = 0
    while True:
        try:
            existing_events = führe_google_api_aus(
                calendar_service.events().list(
                    calendarId=calendar_id,
                    maxResults=2500,
                    singleEvents=True,
                    orderBy='startTime',
                    pageToken=page_token,
                ),
                'Prüfen vorhandener Kalenderereignisse'
            )
        except HttpError as e:
            emit_status(f"❌ Fehler beim Abrufen der Kalenderereignisse: {e}")
            raise

        for event in existing_events.get('items', []):
            if 'summary' in event and 'start' in event and 'date' in event['start']:
                key = (event['summary'], event['start']['date'])
                existing.add(key)

        page_token = existing_events.get('nextPageToken')
        if not page_token:
            break

    for b in events:
        name = b['name']
        d = b['date']
        month = d['month']
        day = d['day']
        year = d.get('year', 2000)
        dt = datetime.date(year, month, day)
        date_str = dt.strftime('%d.%m.%Y')
        event_type = b.get('event_type', 'event')
        label = b.get('label', '')
        if event_type == 'birthday':
            summary = f'🎂 {name}'
        elif event_type == 'anniversary':
            summary = f'💍 {name}'
        else:
            summary = f'🗓️ {label} - {name}' if label else f'🗓️ {name}'
        key = (summary, dt.isoformat())

        if key in existing:
            emit_status(f"⚠️ {label} am {date_str} für {name} bereits vorhanden – übersprungen")
            skipped_count += 1
            continue

        event = {
            'summary': summary,
            'start': {'date': dt.isoformat()},
            'end': {'date': (dt + datetime.timedelta(days=1)).isoformat()},
            'recurrence': ['RRULE:FREQ=YEARLY'],
            'description': f'{label} von {name}' if label else f'Ereignis von {name}',
            'transparency': 'transparent'
        }

        führe_google_api_aus(
            calendar_service.events().insert(calendarId=calendar_id, body=event),
            'Einfügen'
        )
        emit_status(f"✅ {label} am {date_str} für {name} eingetragen")
        created_count += 1
        time.sleep(EINFÜGE_PAUSE_SEKUNDEN)
    return created_count, skipped_count

@app.route('/')
def index():
    return render_template('index.html', csrf_token=hole_csrf_token())

@app.route('/datenschutz')
def privacy():
    return render_template('datenschutz.html')

@app.route('/nutzungsbedingungen')
def terms():
    return render_template('nutzungsbedingungen.html')

def sync_events_ausführen(people_service, calendar_service):
    """Führt den eigentlichen Import aus und meldet den Fortschritt per WebSocket."""
    try:
        all_events = get_all_events(people_service)
        emit_status("✅ Kontakte geladen – bereite Kalender vor...")
        calendar_id = get_or_create_calendar(calendar_service)
        clear_calendar(calendar_service, calendar_id)
        write_events_file(all_events)
        created_count, skipped_count = create_events(calendar_service, calendar_id, all_events)
    except HttpError as fehler:
        status = google_fehler_status(fehler)
        if status == 403 and "SERVICE_DISABLED" in str(fehler):
            emit_status("❌ People API oder Calendar API ist nicht aktiviert. Bitte in der Google Cloud Console einschalten und erneut versuchen.")
        else:
            emit_status(f"❌ Google API Fehler beim Synchronisieren (HTTP {status}): {fehler}")
        return "Error", 500
    except Exception as fehler:
        emit_status(f"❌ Unerwarteter Fehler beim Synchronisieren: {fehler}")
        return "Error", 500

    if skipped_count:
        emit_status(
            f"🎉 Synchronisation abgeschlossen. {created_count} Einträge in den Kalender geschrieben. "
            f"{skipped_count} Einträge waren bereits vorhanden."
        )
    else:
        emit_status(f"🎉 Synchronisation abgeschlossen. {created_count} Einträge in den Kalender geschrieben.")


@app.route('/sync', methods=['POST'])
def sync_events():
    if not csrf_token_ist_gueltig():
        emit_status("❌ Ungültiges CSRF-Token.")
        return "CSRF-Fehler", 400

    people_service, calendar_service, auth_url = get_services()
    if auth_url:
        return jsonify({'auth_url': auth_url}), 401

    sitzungs_id = aktuelle_sitzungs_id()
    if not starte_synchronisation_für_sitzung(sitzungs_id):
        return jsonify({'status': 'läuft_bereits'}), 409

    def synchronisation_im_hintergrund():
        token = AKTIVE_STATUS_SITZUNG.set(sitzungs_id)
        try:
            sync_events_ausführen(people_service, calendar_service)
        finally:
            AKTIVE_STATUS_SITZUNG.reset(token)
            beende_synchronisation_für_sitzung(sitzungs_id)

    socketio.start_background_task(synchronisation_im_hintergrund)
    emit_status("Synchronisation im Hintergrund gestartet.", sitzungs_id=sitzungs_id)
    return jsonify({'status': 'gestartet'}), 202

@app.route('/oauth2callback')
def oauth2callback():
    error = request.args.get('error')
    if error:
        emit_status(f"❌ OAuth-Fehler: {error}")
        return "OAuth-Fehler", 400

    state = request.args.get('state')
    code = request.args.get('code')
    if not state or not code:
        emit_status("❌ OAuth-Callback unvollständig (state oder code fehlt).")
        return "Ungültiger OAuth-Callback", 400

    expected_state = session.get('oauth_state')
    if expected_state != state:
        emit_status("❌ OAuth-Status stimmt nicht mit der Session überein.")
        return "Ungültiger OAuth-Status", 400

    flow = flows.get(state)
    if not flow:
        emit_status("❌ OAuth-Flow nicht gefunden. Bitte erneut starten.")
        return "OAuth-Flow fehlt", 400

    try:
        flow.fetch_token(code=code)
    except Exception as exc:
        emit_status(f"❌ Fehler beim Abrufen des Tokens: {exc}")
        return "OAuth-Fehler", 500

    creds = flow.credentials
    speichere_zugangsdaten(creds)
    flows.pop(state, None)
    session.pop('oauth_state', None)
    emit_status("✅ OAuth erfolgreich abgeschlossen.")
    return redirect(url_for('index', autostart=1))

if __name__ == '__main__':
    socketio.run(
        app,
        debug=umgebung_ist_wahr('FLASK_DEBUG', False),
        port=int(os.environ.get('PORT', '8022')),
        host=os.environ.get('HOST', '0.0.0.0')
    )
