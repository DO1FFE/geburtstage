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

    def test_vorschau_filtert_und_gibt_kein_jahr_aus(self):
        ereignisse = [
            {
                'name': 'Erik Schauer',
                'date': {'year': 1978, 'month': 1, 'day': 11},
                'label': 'Geburtstag',
            },
            {
                'name': 'Anderer Kontakt',
                'date': {'year': 2001, 'month': 5, 'day': 2},
                'label': 'Geburtstag',
            },
        ]

        vorschau = anwendung.erstelle_kontaktvorschau(ereignisse, 2, 'erik')

        self.assertEqual(vorschau['treffer_gesamt'], 1)
        self.assertEqual(vorschau['einträge'][0]['datum'], '11. Januar')
        self.assertNotIn('1978', str(vorschau))

    def test_vorschau_ist_auf_acht_einträge_begrenzt(self):
        ereignisse = [
            {
                'name': f'Kontakt {nummer}',
                'date': {'month': 1, 'day': nummer + 1},
                'label': 'Geburtstag',
            }
            for nummer in range(12)
        ]

        vorschau = anwendung.erstelle_kontaktvorschau(ereignisse, 12)

        self.assertEqual(vorschau['treffer_gesamt'], 12)
        self.assertEqual(len(vorschau['einträge']), 8)

    @patch.object(anwendung, 'get_all_events')
    @patch.object(anwendung, 'get_services')
    def test_vorschau_route_liefert_google_daten(self, get_services, get_all_events):
        get_services.return_value = (object(), object(), None)
        get_all_events.return_value = ([{
            'name': 'Erik Schauer',
            'date': {'year': 1978, 'month': 1, 'day': 11},
            'label': 'Geburtstag',
        }], 1)

        antwort = self.client.post(
            '/vorschau',
            json={'suchbegriff': 'Erik'},
            headers={'X-CSRF-Token': self.csrf_token()},
        )

        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort.get_json()['einträge'][0]['datum'], '11. Januar')

    @patch.object(anwendung, 'get_services')
    def test_vorschau_merkt_oauth_fortsetzung(self, get_services):
        get_services.return_value = (None, None, 'https://accounts.google.test/oauth')

        antwort = self.client.post(
            '/vorschau',
            json={'suchbegriff': 'Erik'},
            headers={'X-CSRF-Token': self.csrf_token()},
        )

        self.assertEqual(antwort.status_code, 401)
        with self.client.session_transaction() as sitzung:
            self.assertEqual(sitzung['oauth_fortsetzung'], 'vorschau')

    def test_vorschau_weist_falsches_csrf_token_ab(self):
        antwort = self.client.post(
            '/vorschau',
            json={},
            headers={'X-CSRF-Token': 'falsch'},
        )

        self.assertEqual(antwort.status_code, 400)

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
    def test_oauth_callback_setzt_vorschau_fort(self, speichere_zugangsdaten):
        fluss = OAuthFluss()
        anwendung.flows['zustand'] = fluss
        with self.client.session_transaction() as sitzung:
            sitzung['oauth_state'] = 'zustand'
            sitzung['oauth_fortsetzung'] = 'vorschau'

        antwort = self.client.get('/oauth2callback?state=zustand&code=code')

        self.assertEqual(antwort.status_code, 302)
        self.assertTrue(antwort.location.endswith('/?autostart=vorschau'))
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

        self.assertIn('contacts.readonly', startseite.get_data(as_text=True))
        self.assertIn('Aufbewahrung und Löschung', datenschutz.get_data(as_text=True))
        self.assertNotIn('pagead2.googlesyndication.com', startseite.get_data(as_text=True))
        self.assertEqual(startseite.headers['X-Frame-Options'], 'DENY')
        self.assertEqual(startseite.headers['X-Content-Type-Options'], 'nosniff')


if __name__ == '__main__':
    unittest.main()

# © 2026 Erik Schauer, do1ffe@darc.de
