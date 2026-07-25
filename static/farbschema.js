(() => {
    const speicherschlüssel = 'geburtstagsimport-farbschema';
    const wurzel = document.documentElement;
    const systemvorgabe = window.matchMedia('(prefers-color-scheme: dark)');

    function gespeichertesFarbschema() {
        try {
            const wert = window.localStorage.getItem(speicherschlüssel);
            return wert === 'hell' || wert === 'dunkel' ? wert : null;
        } catch {
            return null;
        }
    }

    function aktualisiereSchalter() {
        const dunkel = wurzel.dataset.farbschema === 'dunkel';
        document.querySelectorAll('[data-farbschema-schalter]').forEach(schalter => {
            const beschriftung = dunkel ? 'Hellmodus aktivieren' : 'Dunkelmodus aktivieren';
            schalter.setAttribute('aria-label', beschriftung);
            schalter.setAttribute('title', beschriftung);
            schalter.setAttribute('aria-pressed', String(dunkel));
        });
    }

    function setzeFarbschema(farbschema) {
        wurzel.dataset.farbschema = farbschema;
        aktualisiereSchalter();
    }

    const startFarbschema = gespeichertesFarbschema()
        || (systemvorgabe.matches ? 'dunkel' : 'hell');
    setzeFarbschema(startFarbschema);

    document.addEventListener('DOMContentLoaded', () => {
        aktualisiereSchalter();
        document.querySelectorAll('[data-farbschema-schalter]').forEach(schalter => {
            schalter.addEventListener('click', () => {
                const neuesFarbschema =
                    wurzel.dataset.farbschema === 'dunkel' ? 'hell' : 'dunkel';
                try {
                    window.localStorage.setItem(speicherschlüssel, neuesFarbschema);
                } catch {
                    // Das Farbschema funktioniert auch ohne verfügbaren Browserspeicher.
                }
                setzeFarbschema(neuesFarbschema);
            });
        });
    });

    const übernehmeSystemvorgabe = ereignis => {
        if (!gespeichertesFarbschema()) {
            setzeFarbschema(ereignis.matches ? 'dunkel' : 'hell');
        }
    };
    if (typeof systemvorgabe.addEventListener === 'function') {
        systemvorgabe.addEventListener('change', übernehmeSystemvorgabe);
    } else {
        systemvorgabe.addListener(übernehmeSystemvorgabe);
    }
})();

// © 2026 Erik Schauer, do1ffe@darc.de
