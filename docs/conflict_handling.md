# Konfliktverhalten bei "Alle synchronisieren"

## Aktueller Stand
- Während des Exports ruft `sync_events_to_calendar` für jeden Termin den aktuellen Remote-Stand ab und prüft zunächst die ETag-Werte (`remote_state.etag` vs. `event.caldav_etag`).
- Falls kein ETag vorliegt, wird zusätzlich der `last_modified`-Zeitstempel des CalDAV-Objekts mit dem zuletzt bekannten Remote-Zeitstempel bzw. dem letzten Synchronisationszeitpunkt verglichen. Ein späterer Zeitstempel führt zu einem erkannten Konflikt oder – falls keine lokalen Änderungen vorliegen – zum Einspielen des Remote-Snapshots.
- Auf diese Weise verhindern wir, dass Remoteänderungen ohne ETag von Maildaten überschrieben werden.
- Sobald ein Konflikt vorliegt, bleibt er auch nach erneuten E-Mail-Imports bestehen; neue Mail-Updates ändern zwar die lokale Version, schalten den Konflikt aber nicht mehr automatisch frei.

_Relevanter Code: `backend/app/services/event_processor.py`, Abschnitt `sync_events_to_calendar`._

## Auswirkungen auf andere Funktionen
- `perform_sync_all`, AutoSync und der Dialog "Auswahl synchronisieren" verwenden alle `sync_events_to_calendar` und profitieren somit automatisch vom erweiterten Konfliktschutz.

## Offene Punkte
- Liefert der CalDAV-Server weder ETag noch einen verlässlichen `last_modified`-Zeitstempel, können Remoteänderungen weiterhin unbemerkt bleiben. Als Ergänzung wäre ein Payload-Hash-Vergleich denkbar.
