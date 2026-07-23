import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import app as anwendung


class AusführbareAnforderung:
    def __init__(self, ergebnis):
        self.ergebnis = ergebnis

    def execute(self):
        return self.ergebnis


class Verbindungen:
    def __init__(self, seiten):
        self.seiten = list(seiten)

    def list(self, **_):
        return AusführbareAnforderung(self.seiten.pop(0))


class Personen:
    def __init__(self, seiten):
        self.verbindungen = Verbindungen(seiten)

    def connections(self):
        return self.verbindungen


class PersonenDienst:
    def __init__(self, seiten):
        self.personen = Personen(seiten)

    def people(self):
        return self.personen


class OAuthFluss:
    def __init__(self):
        self.credentials = object()
        self.code = None

    def fetch_token(self, code):
        self.code = code


class OAuthStartfluss:
    def __init__(self):
        self.redirect_uri = None
        self.parameter = None

    def authorization_url(self, **parameter):
        self.parameter = parameter
        return 'https://accounts.google.test/oauth', 'neuer-zustand'


class GeburtstagsimportTest(unittest.TestCase):
    def setUp(self):
        anwendung.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.client = anwendung.app.test_client()
        self.client.get('/')

    def csrf_token(self):
        with self.client.session_transaction() as sitzung:
            return sitzung['csrf_token']

    def test_zeitstempel_endet_mit_uhr(self):
        zeitstempel = anwendung.aktueller_zeitstempel()

        self.assertRegex(zeitstempel, r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} Uhr$')
        self.assertNotIn('Europe/Berlin', zeitstempel)
        self.assertNotIn('CEST', zeitstempel)
        self.assertNotIn('CET', zeitstempel)

    def test_kontakte_werden_seitenweise_und_aggregiert_gelesen(self):
        dienst = PersonenDienst([
            {
                'connections': [{
                    'names': [{'displayName': 'Erik Schauer'}],
                    'birthdays': [{'date': {'year': 1978, 'month': 1, 'day': 11}}],
                }],
                'nextPageToken': 'zweite-seite',
            },
            {
                'connections': [{
                    'names': [{'displayName': 'Testkontakt'}],
                    'events': [{
                        'type': 'anniversary',
                        'formattedType': 'Jahrestag',
                        'date': {'year': 2020, 'month': 6, 'day': 3},
                    }],
                }],
            },
        ])

        with anwendung.app.test_request_context('/'):
            ereignisse, kontaktzahl = anwendung.get_all_events(dienst)

        self.assertEqual(kontaktzahl, 2)
        self.assertEqual(len(ereignisse), 2)
        self.assertEqual(ereignisse[0]['label'], 'Geburtstag')
        self.assertEqual(ereignisse[1]['label'], 'Jahrestag')

    @patch.object(anwendung.Flow, 'from_client_secrets_file')
    @patch.object(anwendung, 'lade_zugangsdaten', return_value=None)
    def test_oauth_start_erzwingt_englisch_und_offline_zugriff(
        self,
        lade_zugangsdaten,
        from_client_secrets_file,
    ):
        fluss = OAuthStartfluss()
        from_client_secrets_file.return_value = fluss

        with anwendung.app.test_request_context('/'):
            _, _, auth_url = anwendung.get_services()

        self.assertEqual(auth_url, 'https://accounts.google.test/oauth')
        self.assertEqual(fluss.parameter['hl'], 'en')
        self.assertEqual(fluss.parameter['access_type'], 'offline')
        self.assertEqual(fluss.parameter['prompt'], 'consent')
        from_client_secrets_file.assert_called_once_with(
            anwendung.CREDENTIALS_DATEI,
            scopes=anwendung.SCOPES,
        )
        lade_zugangsdaten.assert_called_once()

    @patch.object(anwendung, 'speichere_zugangsdaten')
    def test_oauth_callback_setzt_synchronisierung_fort(self, speichere_zugangsdaten):
        fluss = OAuthFluss()
        anwendung.flows['zustand'] = fluss
        with self.client.session_transaction() as sitzung:
            sitzung['oauth_state'] = 'zustand'
            sitzung['oauth_fortsetzung'] = 'sync'

        antwort = self.client.get('/oauth2callback?state=zustand&code=code')

        self.assertEqual(antwort.status_code, 302)
        self.assertTrue(antwort.location.endswith('/?autostart=sync'))
        self.assertEqual(fluss.code, 'code')
        speichere_zugangsdaten.assert_called_once_with(fluss.credentials)

    @patch.object(anwendung, 'lösche_zugangsdaten', return_value=True)
    @patch.object(anwendung, 'widerrufe_google_zugang', return_value=True)
    @patch.object(anwendung, 'lade_zugangsdaten', return_value=object())
    def test_google_zugang_wird_widerrufen_und_sitzung_gelöscht(
        self,
        lade_zugangsdaten,
        widerrufe_google_zugang,
        lösche_zugangsdaten,
    ):
        antwort = self.client.post(
            '/zugang-loeschen',
            headers={'X-CSRF-Token': self.csrf_token()},
        )

        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort.get_json()['status'], 'gelöscht')
        lade_zugangsdaten.assert_called_once()
        widerrufe_google_zugang.assert_called_once()
        lösche_zugangsdaten.assert_called_once()
        with self.client.session_transaction() as sitzung:
            self.assertNotIn('sitzungs_id', sitzung)

    def test_abgelaufene_token_datei_wird_entfernt(self):
        with tempfile.TemporaryDirectory() as verzeichnis:
            alter_token = Path(verzeichnis, 'alt.json')
            neuer_token = Path(verzeichnis, 'neu.json')
            alter_token.write_text('{}', encoding='utf-8')
            neuer_token.write_text('{}', encoding='utf-8')
            alt = time.time() - (31 * 24 * 60 * 60)
            os.utime(alter_token, (alt, alt))

            with patch.object(anwendung, 'TOKEN_SPEICHER_DIR', verzeichnis), patch.object(
                anwendung,
                'OAUTH_TOKEN_AUFBEWAHRUNG_TAGE',
                30,
            ):
                anzahl = anwendung.bereinige_token_speicher()

            self.assertEqual(anzahl, 1)
            self.assertFalse(alter_token.exists())
            self.assertTrue(neuer_token.exists())

    def test_seiten_enthalten_datenschutz_und_sicherheitskopfzeilen(self):
        startseite = self.client.get('/')
        datenschutz = self.client.get('/datenschutz')

        self.assertNotIn('Kontaktvorschau', startseite.get_data(as_text=True))
        self.assertNotIn('contacts.readonly', startseite.get_data(as_text=True))
        self.assertEqual(self.client.post('/vorschau').status_code, 404)
        self.assertIn('Aufbewahrung und Löschung', datenschutz.get_data(as_text=True))
        self.assertNotIn('pagead2.googlesyndication.com', startseite.get_data(as_text=True))
        self.assertEqual(startseite.headers['X-Frame-Options'], 'DENY')
        self.assertEqual(startseite.headers['X-Content-Type-Options'], 'nosniff')


if __name__ == '__main__':
    unittest.main()

# © 2026 Erik Schauer, do1ffe@darc.de
