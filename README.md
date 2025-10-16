# CalSync

CalSync synchronisiert Kalendereinladungen aus frei definierbaren IMAP-Ordnern
mit CalDAV-Kalendern. Das Projekt kombiniert ein FastAPI-Backend mit
Hintergrundscheduler und eine React/Vite-Weboberfläche zur Verwaltung der
Konten sowie zur manuellen Steuerung der Synchronisation.

## Inhaltsverzeichnis
- [Architekturüberblick](#architekturüberblick)
- [Funktionsumfang](#funktionsumfang)
- [Systemvoraussetzungen](#systemvoraussetzungen)
- [Schnellstart mit Docker](#schnellstart-mit-docker)
- [Manueller Betrieb ohne Docker](#manueller-betrieb-ohne-docker)
- [Konfiguration über Umgebungsvariablen](#konfiguration-über-umgebungsvariablen)
- [Datenpersistenz und Upgrades](#datenpersistenz-und-upgrades)
- [Betriebshinweise](#betriebshinweise)
- [API-Dokumentation](#api-dokumentation)
- [Tests & Qualitätssicherung](#tests--qualitätssicherung)
- [Sicherheitshinweise](#sicherheitshinweise)
- [Lizenz](#lizenz)

## Architekturüberblick

- **Backend** (`backend/`)
  - FastAPI-Server mit REST-API für Konfiguration, Scans und Exporte
  - SQLite-Datenbank (SQLAlchemy) zur Speicherung von Konten und Events
  - IMAP- und CalDAV-Clients inklusive Verbindungstests
  - APScheduler als Hintergrunddienst für Auto-Sync-Läufe
- **Frontend** (`web/`)
  - React + Vite + TailwindCSS Dashboard
  - Deutschsprachige Benutzeroberfläche für Konten, Ordner-Mapping und Sync-Steuerung
- **Docker Compose** (`docker-compose.yml`)
  - Startet Backend, Web-UI und optional Mailhog als Test-Mailserver

## Funktionsumfang

- Verwaltung von IMAP- und CalDAV-Zugangsdaten inkl. Inline-Verbindungstests
- Konfiguration von Ordner-Kalender-Zuordnungen mit manueller und automatischer Synchronisation
- Konfliktmanagement für bereits existierende Events im CalDAV-Kalender
- Protokollierung relevanter Aktionen über das Python-Logging-Framework
- Optionales Löschen verarbeiteter Einladungen direkt aus dem IMAP-Postfach

## Systemvoraussetzungen

| Komponente           | Version/Empfehlung         |
| -------------------- | -------------------------- |
| Docker & Compose     | Docker Engine ≥ 24, Compose ≥ 2 |
| Python (Backend dev) | 3.11                       |
| Node.js (Frontend)   | 20 LTS                     |
| SQLite               | Wird automatisch durch Python geliefert |

## Schnellstart mit Docker

1. **Repository klonen und Variablen setzen**
   ```bash
   git clone https://github.com/<organisation>/calsync.git
   cd calsync
   cp env.example .env
   # Passe Werte in .env nach Bedarf an (API-URL, Zeitzone, IMAP-Timeout ...)
   ```

2. **Services bauen und starten**
   ```bash
   docker compose up --build
   ```

3. **Zugriffspunkte**
   - Backend API (Swagger UI): http://localhost:8000/docs
   - Web UI (Vite Preview): http://localhost:4173
   - Mailhog (Test-Mailserver): http://localhost:8025

> 💡 **Hinweis:** Das Backend setzt `PIP_DEFAULT_TIMEOUT=120`, damit Paketinstallationen
> auch bei langsamen Verbindungen stabil bleiben. Übernehme diesen Wert in abgeleiteten
> Dockerfiles.

## Manueller Betrieb ohne Docker

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../env.example ../.env  # optional, falls noch nicht vorhanden
export $(grep -v '^#' ../.env | xargs)  # lädt Variablen ins aktuelle Shell-Environment
uvicorn app.main:app --reload
```

Die API ist anschließend unter http://localhost:8000 erreichbar.

### Frontend

```bash
cd web
npm install
npm run dev
```

Der Vite-Dev-Server läuft unter http://localhost:5173 und proxyt alle `/api`-Anfragen
standardmäßig auf http://localhost:8000.

## Konfiguration über Umgebungsvariablen

Kopiere `env.example` nach `.env` und passe die Werte an deine Umgebung an.
Docker Compose lädt `.env` automatisch, lokale Shell-Sessions benötigen ein `export`.

| Variable             | Bereich     | Beschreibung |
| -------------------- | ----------- | ------------ |
| `TZ`                 | global      | Zeitzone für Container und Scheduler (Standard: `Europe/Berlin`). |
| `IMAP_CLIENT_TIMEOUT`| Backend     | Timeout in Sekunden für IMAP-Verbindungen. Verwende höhere Werte bei langsamen Servern (Standard: `180`). |
| `VITE_API_BASE`      | Frontend    | Öffentliche Basis-URL für API-Aufrufe. Für gemeinsam ausgelieferte Frontend/Backend-Setups auf `/api` belassen, sonst absolute URL setzen. |

## Datenpersistenz und Upgrades

- Standardmäßig nutzt das Backend eine SQLite-Datenbank unter `backend/data/calsync.db`.
- Im Docker-Setup persistiert das Volume `backend-data` die Daten über Container-Neustarts.
- Schema-Änderungen werden beim Start automatisch über `apply_schema_upgrades()` angewendet.
- Sichere die SQLite-Datei regelmäßig oder migriere zu einer externen Datenbank, wenn höhere
  Verfügbarkeit benötigt wird.

## Betriebshinweise

- **Auto-Sync:** Der Scheduler prüft alle fünf Minuten auf neue Einladungen, sobald Auto-Sync
  in der UI aktiviert wurde. Überwache das Backend-Log (`docker compose logs backend`) für Statusmeldungen.
- **Logging:** Das Backend nutzt das Python-Logging-Modul (`logging.INFO`). Für produktive Setups
  empfiehlt sich ein zentralisiertes Log-Management oder die Anbindung an Systemd/Journald.
- **Health Checks:** `GET /health` liefert einen einfachen Liveness-Check und kann in Load-Balancer- oder
  Monitoring-Systeme integriert werden.
- **Reverse Proxy:** Setze in Produktion einen Proxy (z.B. Nginx, Traefik) vor die Services und leite `/api`
  an das Backend weiter. Stelle TLS für externe Zugriffe bereit.

## API-Dokumentation

### Allgemeines

- Basis-URL im Docker-Setup: `http://localhost:8000`
- Interaktive OpenAPI-Dokumentation: `GET /docs` (Swagger UI) und `GET /redoc`
- Die REST-API ist nicht authentifiziert. In produktiven Umgebungen sollte der Reverse Proxy die Absicherung übernehmen.

### Gesundheitscheck

| Methode | Pfad      | Beschreibung                                | Antwort |
| ------- | --------- | ------------------------------------------- | ------- |
| GET     | `/health` | Einfache Liveness-Prüfung des Backends.     | `{ "status": "ok" }` |

### Kontenverwaltung

| Methode | Pfad                               | Beschreibung                                                         | Wichtige Request-Daten |
| ------- | ---------------------------------- | -------------------------------------------------------------------- | ---------------------- |
| GET     | `/accounts`                        | Listet alle konfigurierten IMAP- und CalDAV-Konten.                  | — |
| POST    | `/accounts`                        | Legt ein neues Konto an.                                             | `AccountCreate` mit `label`, `type` (`imap`/`caldav`), `settings`, optional `imap_folders` |
| PUT     | `/accounts/{account_id}`           | Aktualisiert ein bestehendes Konto.                                  | `AccountUpdate` identisch zu `AccountCreate` |
| DELETE  | `/accounts/{account_id}`           | Entfernt ein Konto sowie abhängige Sync-Mappings und Events.         | — |
| POST    | `/accounts/test`                   | Führt einen Verbindungscheck für IMAP- oder CalDAV-Zugangsdaten aus. | `ConnectionTestRequest` mit `type` und `settings` |
| GET     | `/accounts/{account_id}/calendars` | Liest verfügbare Kalender eines CalDAV-Kontos.                        | — |

**Hinweise zu den Settings**

- IMAP erwartet Felder wie `host`, `username`, `password`, optional `port`, `ssl`, `timeout` und eine optionale `folders`-Liste.
- CalDAV erwartet Felder wie `url`, `username`, `password` sowie optionale Client-Konfigurationswerte.
- Für IMAP-Konten können `imap_folders` mit `name` und `include_subfolders` angegeben werden; bei CalDAV-Konten werden sie ignoriert.

### Kalender-Ereignisse

| Methode | Pfad                                             | Beschreibung                                                                                  | Wichtige Request-Daten |
| ------- | ------------------------------------------------ | --------------------------------------------------------------------------------------------- | ---------------------- |
| GET     | `/events`                                        | Listet alle verfolgten Einladungen inklusive Historie, Konflikten und Sync-Status.            | — |
| POST    | `/events/scan`                                   | Startet einen Postfach-Scan im Hintergrund.                                                   | — (Async-Job, liefert `SyncJobStatus`) |
| POST    | `/events/manual-sync`                            | Synchronisiert ausgewählte Events sofort in den Zielkalender.                                 | `ManualSyncRequest` mit `event_ids` |
| POST    | `/events/{event_id}/response`                    | Aktualisiert die Teilnahmeantwort (z.B. akzeptiert/abgelehnt).                                | `EventResponseUpdate` mit `response` (`accepted`, `declined`, `tentative`, `none`) |
| POST    | `/events/{event_id}/resolve-conflict`            | Löst Synchronisationskonflikte anhand einer gewählten Option auf und synchronisiert erneut.   | `ConflictResolutionRequest` mit `action` und optionalen `selections` |
| POST    | `/events/{event_id}/disable-tracking`            | Deaktiviert die Nachverfolgung für ein Event.                                                 | — |
| POST    | `/events/{event_id}/delete-mail`                 | Entfernt die verknüpfte Einladung aus dem IMAP-Postfach.                                      | — |

Antworten liefern jeweils das aktualisierte `TrackedEvent` inklusive Feldern wie `status`, `response_status`, `sync_state`, `conflicts`, `attendees` und Historie.

### Auto-Sync, Scheduler und Jobs

| Methode | Pfad                     | Beschreibung                                                                 | Wichtige Request-Daten |
| ------- | ------------------------ | ---------------------------------------------------------------------------- | ---------------------- |
| POST    | `/events/schedule`       | Plant einen periodischen Scan/Synchronisationsjob in `minutes`-Abständen.    | Query-Parameter `minutes` (Standard: 5) |
| POST    | `/events/sync-all`       | Stößt einen vollständigen Sync aller aktiven Mappings an.                    | — (Async-Job, liefert `SyncJobStatus`) |
| GET     | `/events/auto-sync`      | Liefert den Status des Auto-Syncs inkl. aktivem Job und Antwort-Strategie.   | — |
| POST    | `/events/auto-sync`      | Aktiviert/deaktiviert Auto-Sync und konfiguriert Intervall sowie Auto-Response. | `AutoSyncRequest` mit `enabled`, `interval_minutes` (1–720), `auto_response` |
| GET     | `/jobs/{job_id}`         | Fragt den Fortschritt eines Hintergrundjobs ab.                              | — |

`SyncJobStatus` umfasst `job_id`, `status` (`queued`, `running`, `finished`, `failed`), optionale Fortschrittswerte (`processed`, `total`) sowie Detailinformationen zur aktuellen Phase (`detail`).
`AutoSyncStatus` liefert zusätzlich `enabled`, `interval_minutes`, die konfigurierte automatische Antwort sowie optional `active_job` mit dem zuletzt gestarteten Hintergrundjob.

### Sync-Mappings

| Methode | Pfad                              | Beschreibung                                                           | Wichtige Request-Daten |
| ------- | --------------------------------- | ---------------------------------------------------------------------- | ---------------------- |
| GET     | `/sync-mappings`                  | Listet alle IMAP-zu-CalDAV-Zuordnungen.                                | — |
| POST    | `/sync-mappings`                  | Legt eine neue Zuordnung an.                                           | `SyncMappingCreate` mit Konto-IDs, `imap_folder`, `calendar_url`, optional `calendar_name` |
| PUT     | `/sync-mappings/{mapping_id}`     | Aktualisiert Kalender-URL oder Anzeigenamen einer Zuordnung.           | `SyncMappingUpdate` mit optionalem `calendar_url`, `calendar_name` |
| DELETE  | `/sync-mappings/{mapping_id}`     | Entfernt eine Zuordnung dauerhaft.                                     | — |

## Tests & Qualitätssicherung

- Aktuell existieren keine automatisierten Tests. Nutze die Swagger-UI sowie manuelle Tests über die Weboberfläche.
- Für Backend-Erweiterungen sollten Unit- oder Integrationstests mit `pytest` ergänzt werden.
- Frontend-Anpassungen lassen sich mit `npm run lint` und optional Playwright/Cypress-Tests absichern (noch nicht konfiguriert).

## Sicherheitshinweise

- Hinterlege produktive Zugangsdaten über Secrets oder verschlüsselte Variablen und nicht in JSON-Konfigurationen.
- Erzwinge TLS für IMAP- und CalDAV-Verbindungen und setze Zertifikatsprüfung nicht außer Kraft.
- Schütze die Weboberfläche durch Authentifizierung (z.B. Basic Auth über den Reverse Proxy) sowie IP-Filter.
- Prüfe regelmäßig Mailserver-Logs, um unautorisierte Zugriffe frühzeitig zu erkennen.

## Lizenz

GNU General Public License v3.0 (siehe `LICENSE`)
