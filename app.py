import os
import datetime
import pickle
import signal
import sys

import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import time

SCOPES = [
    'https://www.googleapis.com/auth/contacts.readonly',
    'https://www.googleapis.com/auth/calendar'
]

# Print all messages to console when True. When False only important
# messages are shown.
VERBOSE_CONSOLE = False


app = Flask(__name__)
socketio = SocketIO(app, async_mode='eventlet')

def emit_status(msg):
    """Send a status message to the web UI and optionally print it."""
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"{timestamp} - {msg}"
    socketio.emit('status', line)
    important = any(x in msg for x in ('⚠️', '❌', '🎉', 'Server'))
    if VERBOSE_CONSOLE or important:
        print(line, flush=True)

def handle_sigint(sig, frame):
    """Gracefully stop the server when CTRL-C is pressed."""
    emit_status("Server wird beendet...")
    socketio.stop()
    sys.exit(0)

signal.signal(signal.SIGINT, handle_sigint)

flow = None  # keep OAuth flow between requests

def get_services(auth_code=None):
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)

    global flow
    if not creds or not creds.valid:
        if auth_code:
            if not flow:
                raise RuntimeError("OAuth flow not initialized")
            flow.fetch_token(code=auth_code)
            creds = flow.credentials
            with open('token.pickle', 'wb') as token:
                pickle.dump(creds, token)
        else:
            emit_status("Authentifiziere Benutzer über Google...")
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            # Explicit redirect URI required since run_console() is not used
            flow.redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'
            auth_url, _ = flow.authorization_url(prompt='consent')
            return None, None, auth_url

    people_service = build('people', 'v1', credentials=creds)
    calendar_service = build('calendar', 'v3', credentials=creds)
    return people_service, calendar_service, None

def get_or_create_calendar(service, name="Geburtstage"):
    emit_status(f"Suche nach Kalender '{name}'...")
    calendars = service.calendarList().list().execute()
    for cal in calendars['items']:
        if cal['summary'].lower() == name.lower():
            emit_status("Kalender bereits vorhanden.")
            return cal['id']

    emit_status("Kalender nicht gefunden – wird erstellt.")
    new_cal = {'summary': name, 'timeZone': 'Europe/Berlin'}
    created = service.calendars().insert(body=new_cal).execute()
    return created['id']

def clear_calendar(service, calendar_id):
    """Remove all events from the given calendar."""
    emit_status("Lösche vorhandene Einträge im Kalender...")
    page_token = None
    deleted_any = False
    while True:
        try:
            events = service.events().list(
                calendarId=calendar_id,
                pageToken=page_token,
                maxResults=2500,
            ).execute()
        except HttpError as e:
            emit_status(f"❌ Fehler beim Abrufen der Kalenderereignisse: {e}")
            raise

        for ev in events.get('items', []):
            while True:
                try:
                    service.events().delete(calendarId=calendar_id, eventId=ev['id']).execute()
                    deleted_any = True
                    time.sleep(0.1)
                    break
                except HttpError as e:
                    if e.resp.status == 403 and 'rateLimitExceeded' in str(e):
                        emit_status('⏳ Warte wegen Google Rate Limit...')
                        time.sleep(2)
                    else:
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
        results = people_service.people().connections().list(
            resourceName='people/me',
            personFields='names,birthdays,events',
            pageSize=1000,
            pageToken=page_token
        ).execute()

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
    existing_events = calendar_service.events().list(
        calendarId=calendar_id,
        maxResults=2500,
        singleEvents=True,
        orderBy='startTime'
    ).execute()

    existing = set()
    for event in existing_events.get('items', []):
        if 'summary' in event and 'start' in event and 'date' in event['start']:
            key = (event['summary'], event['start']['date'])
            existing.add(key)

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
            continue

        event = {
            'summary': summary,
            'start': {'date': dt.isoformat()},
            'end': {'date': (dt + datetime.timedelta(days=1)).isoformat()},
            'recurrence': ['RRULE:FREQ=YEARLY'],
            'description': f'{label} von {name}' if label else f'Ereignis von {name}',
            'transparency': 'transparent'
        }

        while True:
            try:
                calendar_service.events().insert(calendarId=calendar_id, body=event).execute()
                emit_status(f"✅ {label} am {date_str} für {name} eingetragen")
                time.sleep(1)
                break
            except HttpError as e:
                if e.resp.status == 403 and 'rateLimitExceeded' in str(e):
                    emit_status('⏳ Warte wegen Google Rate Limit...')
                    time.sleep(2)
                else:
                    raise

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/sync')
def sync_events():
    people_service, calendar_service, auth_url = get_services()
    if auth_url:
        return jsonify({'auth_url': auth_url}), 401
    calendar_id = get_or_create_calendar(calendar_service)
    clear_calendar(calendar_service, calendar_id)
    try:
        all_events = get_all_events(people_service)
    except HttpError as e:
        if e.resp.status == 403 and "SERVICE_DISABLED" in str(e):
            emit_status("❌ People API oder Calendar API ist nicht aktiviert. Bitte in der Google Cloud Console einschalten und erneut versuchen.")
        else:
            emit_status(f"❌ Fehler beim Abrufen der Kontakte: {e}")
        return "Error", 500
    write_events_file(all_events)
    try:
        create_events(calendar_service, calendar_id, all_events)
    except HttpError as e:
        emit_status(f"❌ Fehler beim Erstellen der Events: {e}")
        return "Error", 500
    emit_status("🎉 Synchronisation abgeschlossen.")
    return "OK"

@app.route('/auth', methods=['POST'])
def submit_code():
    code = request.json.get('code')
    get_services(auth_code=code)
    return 'OK'

if __name__ == '__main__':
    socketio.run(app, debug=True, port=8022, host="0.0.0.0")
