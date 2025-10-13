# CalSync

CalSync ist ein leichtgewichtiger Service, der definierbare IMAP-Ordner nach Kalendereinladungen durchsucht und gefundene Termine mit CalDAV-Kalendern synchronisiert. Die Lösung besteht aus einem FastAPI-Backend mit Hintergrundscheduler sowie einer React/Vite-Weboberfläche zur Verwaltung der Konten und zum manuellen Export.

## Architekturüberblick

- **Backend** (`backend/`)
  - FastAPI-Server mit REST-API für Konfiguration, Scans und Exporte
  - SQLite-Datenbank (per SQLAlchemy) zur Speicherung von Konten und gefundenen Terminen
  - IMAP- und CalDAV-Clients inkl. Verbindungstests
  - Hintergrundscheduler (APScheduler) für automatische Scans
- **Frontend** (`web/`)
  - React + Vite + TailwindCSS Dashboard
  - Verwaltung von IMAP-/CalDAV-Konten, Verbindungstests und manueller Export
- **Docker Compose** (`docker-compose.yml`)
  - Startet Backend, Web-UI und optionale Mailhog-Testumgebung

## Schnellstart

1. **Voraussetzungen**
   - Docker und Docker Compose

2. **Projekt starten**
   ```bash
   docker compose up --build
   ```

3. **Zugriff**
   - Backend API: http://localhost:8000/docs
   - Web UI: http://localhost:4173
   - Mailhog (Test-Mailserver): http://localhost:8025

## Entwicklung ohne Docker

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Frontend

```bash
cd web
npm install
npm run dev
```

## Wichtige Endpunkte

| Methode | Pfad              | Beschreibung                                  |
| ------ | ----------------- | --------------------------------------------- |
| GET    | `/health`         | Gesundheitscheck                              |
| GET    | `/accounts`       | Auflistung aller Konten                       |
| POST   | `/accounts`       | Neues Konto anlegen                           |
| POST   | `/accounts/test`  | Verbindungstest für IMAP oder CalDAV          |
| GET    | `/events`         | Gefundene Termine anzeigen                    |
| POST   | `/events/scan`    | Manuelles Scannen der IMAP-Ordner             |
| POST   | `/events/manual-sync` | Manuelle Übertragung in CalDAV-Kalender |
| POST   | `/events/schedule`    | Automatische Scans planen                 |

## Datenpersistenz

Das Backend speichert alle Daten in einer SQLite-Datenbank unter `backend/data/calsync.db`. Im Docker-Setup wird dieser Pfad über das Volume `backend-data` persistiert.

## Tests

Aktuell sind keine automatisierten Tests definiert. Verwenden Sie `docker compose up` bzw. manuelles Testen über die UI/Swagger-Oberfläche.

## Sicherheitshinweise

- Speichern Sie Produktiv-Zugangsdaten nicht im Klartext-JSON. Nutzen Sie Umgebungsvariablen oder Secrets-Management.
- Aktivieren Sie TLS für CalDAV und IMAP-Verbindungen in produktiven Setups.
- Setzen Sie Zugriffskontrollen vor die Weboberfläche (Reverse Proxy, Authentifizierung).

## Lizenz

MIT-Lizenz (siehe `LICENSE`, falls vorhanden).
