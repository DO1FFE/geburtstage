import os
import datetime
import pickle
import logging
from flask import Flask, render_template
from flask_socketio import SocketIO
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/contacts.readonly',
    'https://www.googleapis.com/auth/calendar'
]

# Logging konfigurieren
logging.basicConfig(
    filename='log.txt',
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

app = Flask(__name__)
socketio = SocketIO(app)

def emit_status(msg):
    socketio.emit('status', msg)
    print(msg)
    logging.info(msg)

def get_services():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        emit_status("Authentifiziere Benutzer über Google...")
        flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
        creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    people_service = build('people', 'v1', credentials=creds)
    calendar_service = build('calendar', 'v3', credentials=creds)
    return people_service, calendar_service

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

def get_birthdays(people_service):
    emit_status("Lese Kontakte und Geburtstage...")
    results = people_service.people().connections().list(
        resourceName='people/me',
        personFields='names,birthdays',
        pageSize=1000
    ).execute()

    birthdays = []
    for person in results.get('connections', []):
        names = person.get('names', [])
        bdays = person.get('birthdays', [])
        if names and bdays:
            name = names[0].get('displayName')
            for b in bdays:
                date = b.get('date')
                if date and date.get('month') and date.get('day'):
                    birthdays.append({'name': name, 'date': date})
    return birthdays

def create_events(calendar_service, calendar_id, birthdays):
    emit_status("Prüfe vorhandene Geburtstage im Kalender...")
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

    for b in birthdays:
        name = b['name']
        d = b['date']
        month = d['month']
        day = d['day']
        year = d.get('year', 2000)
        dt = datetime.date(year, month, day)
        summary = f'🎂 {name}'
        key = (summary, dt.isoformat())

        if key in existing:
            emit_status(f"⚠️ Geburtstag von {name} bereits vorhanden – übersprungen")
            continue

        event = {
            'summary': summary,
            'start': {'date': dt.isoformat()},
            'end': {'date': (dt + datetime.timedelta(days=1)).isoformat()},
            'recurrence': ['RRULE:FREQ=YEARLY'],
            'description': f'Geburtstag von {name}',
            'transparency': 'transparent'
        }

        calendar_service.events().insert(calendarId=calendar_id, body=event).execute()
        emit_status(f"✅ Geburtstag von {name} hinzugefügt")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/sync')
def sync_birthdays():
    people_service, calendar_service = get_services()
    calendar_id = get_or_create_calendar(calendar_service)
    birthdays = get_birthdays(people_service)
    create_events(calendar_service, calendar_id, birthdays)
    emit_status("🎉 Synchronisation abgeschlossen.")
    return "OK"

if __name__ == '__main__':
    socketio.run(app, debug=True)
