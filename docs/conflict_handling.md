# Konfliktverhalten bei "Alle synchronisieren"

## Beobachtung
- Während des Exports ruft `sync_events_to_calendar` für jeden Termin den aktuellen Remote-Stand ab und vergleicht ausschließlich die ETag-Werte (`remote_state.etag` vs. `event.caldav_etag`).
- Fehlt einer der Werte (z. B. weil der Server keine `getetag`-Eigenschaft liefert oder weil wir bisher keinen ETag gespeichert haben), wird der Vergleich übersprungen und der Termin ungeprüft hochgeladen.
- Somit werden Änderungen, die direkt im CalDAV-Kalender vorgenommen wurden, nicht erkannt und von den Maildaten überschrieben.

_Relevanter Code: `backend/app/services/event_processor.py`, Zeilen 240–262._

## Auswirkungen auf andere Funktionen
- `perform_sync_all` und damit AutoSync rufen intern ebenfalls `sync_events_to_calendar` auf, wodurch dieselbe Lücke greift.
- Der Dialog "Auswahl synchronisieren" (manuelles Syncen) gruppiert die Termine nach Mapping, ruft anschließend ebenfalls `sync_events_to_calendar` auf und ist daher gleichermaßen betroffen.

## Lösungsansatz
1. **Fallback auf Änderungszeitpunkte**: Wenn kein ETag vorliegt, sollte ein Vergleich über `remote_state.last_modified` (ggf. normalisiert) gegen den gespeicherten `event.remote_last_modified` erfolgen. Ein späterer Zeitpunkt signalisiert eine Remoteänderung.
2. **Snapshot-Vergleich**: Falls der Server weder ETag noch `getlastmodified` liefert, kann ein Hash (z. B. SHA-256) des Remote-Payloads mit dem zuletzt synchronisierten Stand verglichen werden.
3. **Konfliktbehandlung vereinheitlichen**: Wird eine Abweichung erkannt, sollte `_record_sync_conflict` aufgerufen werden, damit der Termin in den manuellen Konflikt-Workflow fällt. Erfolgt der Upload ohne lokale Änderungen, kann `_apply_remote_snapshot` die Remoteversion übernehmen.

Mit diesen Ergänzungen bleibt das bestehende Verhalten bei vollständigen Metadaten unverändert, und gleichzeitig werden Remoteänderungen auch dann erkannt, wenn der Server keine ETags liefert.
