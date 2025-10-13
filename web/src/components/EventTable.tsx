import { useEffect, useMemo, useState } from 'react';
import {
  ManualSyncMissingDetail,
  ManualSyncRequest,
  ManualSyncResponse,
  TrackedEvent,
} from '../types/api';

interface Props {
  events: TrackedEvent[];
  onManualSync: (payload: ManualSyncRequest) => Promise<ManualSyncResponse>;
  onScan: () => Promise<void>;
  onSyncAll: () => Promise<void>;
  autoSyncEnabled: boolean;
  autoSyncResponse: TrackedEvent['response_status'];
  onAutoSyncToggle: (enabled: boolean) => Promise<void>;
  onAutoSyncResponseChange: (response: TrackedEvent['response_status']) => Promise<void>;
  onRespondToEvent: (
    eventId: number,
    response: TrackedEvent['response_status'],
  ) => Promise<TrackedEvent>;
  loading?: boolean;
}

const statusLabelMap: Record<TrackedEvent['status'], string> = {
  new: 'Neu',
  updated: 'Aktualisiert',
  cancelled: 'Abgesagt',
  synced: 'Synchronisiert',
};

const statusStyleMap: Record<TrackedEvent['status'], string> = {
  new: 'bg-sky-500/10 text-sky-300',
  updated: 'bg-indigo-500/10 text-indigo-300',
  cancelled: 'bg-rose-500/10 text-rose-300',
  synced: 'bg-emerald-500/10 text-emerald-300',
};

const responseLabelMap: Record<TrackedEvent['response_status'], string> = {
  none: 'Keine Antwort',
  accepted: 'Zusage',
  tentative: 'Vielleicht',
  declined: 'Absage',
};

const responseStyleMap: Record<TrackedEvent['response_status'], string> = {
  none: 'bg-slate-800 text-slate-200',
  accepted: 'bg-emerald-500/15 text-emerald-300',
  tentative: 'bg-amber-500/15 text-amber-300',
  declined: 'bg-rose-500/15 text-rose-300',
};

const responseActions: Array<{
  value: TrackedEvent['response_status'];
  label: string;
  className: string;
}> = [
  { value: 'accepted', label: 'Zusage', className: 'bg-emerald-500 text-emerald-950 hover:bg-emerald-400' },
  { value: 'tentative', label: 'Vielleicht', className: 'bg-amber-500 text-amber-950 hover:bg-amber-400' },
  { value: 'declined', label: 'Absagen', className: 'bg-rose-500 text-rose-100 hover:bg-rose-400' },
];

function formatDateTime(value?: string) {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return date.toLocaleString();
}

function formatDateRange(event: TrackedEvent) {
  const start = formatDateTime(event.start);
  const end = formatDateTime(event.end);
  if (start && end) {
    return `${start} – ${end}`;
  }
  return start ?? end ?? 'Kein Zeitraum bekannt';
}

function formatConflictRange(conflict: TrackedEvent['conflicts'][number]) {
  const start = formatDateTime(conflict.start);
  const end = formatDateTime(conflict.end);
  if (start && end) {
    return `${start} – ${end}`;
  }
  return start ?? end ?? 'Keine Zeitangabe';
}

export default function EventTable({
  events,
  onManualSync,
  onScan,
  onSyncAll,
  autoSyncEnabled,
  autoSyncResponse,
  onAutoSyncToggle,
  onAutoSyncResponseChange,
  onRespondToEvent,
  loading = false,
}: Props) {
  const [selected, setSelected] = useState<number[]>([]);
  const [openItems, setOpenItems] = useState<number[]>([]);
  const [syncResult, setSyncResult] = useState<string[]>([]);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [syncNotice, setSyncNotice] = useState<string | null>(null);
  const [missing, setMissing] = useState<ManualSyncMissingDetail[]>([]);
  const [busy, setBusy] = useState(false);
  const [respondingId, setRespondingId] = useState<number | null>(null);
  const [searchTerm, setSearchTerm] = useState('');

  // Remove selections for events that disappeared after refresh.
  useEffect(() => {
    setSelected((prev) => prev.filter((id) => events.some((event) => event.id === id)));
    setOpenItems((prev) => prev.filter((id) => events.some((event) => event.id === id)));
  }, [events]);

  // Derive filtered event list based on search input for responsive UI updates.
  const filteredEvents = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    if (!term) {
      return events;
    }
    return events.filter((event) => {
      const haystack = [
        event.summary ?? '',
        event.uid,
        event.organizer ?? '',
        event.source_folder ?? '',
        event.status,
        event.response_status,
        event.source_account_id ? String(event.source_account_id) : '',
        event.conflicts?.map((conflict) => conflict.summary ?? conflict.uid).join(' ') ?? '',
      ]
        .join(' ')
        .toLowerCase();
      return haystack.includes(term);
    });
  }, [events, searchTerm]);

  // Aggregate key performance indicators for the overview widgets.
  const metrics = useMemo(() => {
    const outstanding = events.filter(
      (event) => event.status === 'new' || event.status === 'updated',
    ).length;
    const processed = events.filter((event) => event.status === 'synced').length;
    const cancelled = events.filter((event) => event.status === 'cancelled').length;
    const awaitingDecision = events.filter(
      (event) => event.response_status === 'none' && event.status !== 'cancelled',
    ).length;
    const conflicts = events.filter((event) => (event.conflicts?.length ?? 0) > 0).length;
    const todayStart = new Date();
    todayStart.setHours(0, 0, 0, 0);
    const todayEnd = new Date();
    todayEnd.setHours(23, 59, 59, 999);
    const today = events.filter((event) => {
      if (!event.start) {
        return false;
      }
      const startDate = new Date(event.start);
      return startDate >= todayStart && startDate <= todayEnd;
    }).length;
    return { outstanding, processed, cancelled, awaitingDecision, today, conflicts };
  }, [events]);

  function toggleSelection(id: number) {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id],
    );
  }

  function toggleOpen(id: number) {
    setOpenItems((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id],
    );
  }

  async function handleSyncSelection() {
    if (selected.length === 0) {
      return;
    }
    setBusy(true);
    setSyncError(null);
    setSyncNotice(null);
    setMissing([]);
    try {
      const payload: ManualSyncRequest = { event_ids: selected };
      const result = await onManualSync(payload);
      setSyncResult(result.uploaded);
      setMissing(result.missing ?? []);
      if (result.missing && result.missing.length > 0) {
        setSyncError('Für einige Termine existiert keine Sync-Zuordnung.');
        setSelected(result.missing.map((item) => item.event_id));
      } else {
        setSyncError(null);
        setSelected([]);
      }
      if (result.uploaded.length > 0) {
        setSyncNotice('Ausgewählte Termine wurden synchronisiert.');
      } else if (!result.missing?.length) {
        setSyncError('Keine Termine konnten synchronisiert werden.');
      }
    } catch (error: any) {
      setSyncResult([]);
      setSyncNotice(null);
      const detail = error?.response?.data?.detail;
      if (typeof detail === 'string') {
        setSyncError(detail);
      } else if (detail && typeof detail.message === 'string') {
        setSyncError(detail.message);
        if (Array.isArray(detail.missing)) {
          setMissing(
            detail.missing.map((item: any) => ({
              uid: item?.uid,
              reason: item?.reason,
              account_id: item?.account_id,
              folder: item?.folder,
              event_id: Number(item?.event_id ?? 0),
            })),
          );
        }
      } else {
        setSyncError('Synchronisation fehlgeschlagen.');
      }
    } finally {
      setBusy(false);
    }
  }

  async function handleSyncAll() {
    setBusy(true);
    try {
      await onSyncAll();
    } finally {
      setBusy(false);
    }
  }

  async function handleScan() {
    setBusy(true);
    try {
      await onScan();
    } finally {
      setBusy(false);
    }
  }

  async function handleAutoSyncToggle() {
    setBusy(true);
    try {
      await onAutoSyncToggle(!autoSyncEnabled);
    } finally {
      setBusy(false);
    }
  }

  async function handleAutoResponseToggle() {
    setBusy(true);
    setSyncError(null);
    setSyncResult([]);
    setMissing([]);
    try {
      const next = autoSyncResponse === 'accepted' ? 'none' : 'accepted';
      await onAutoSyncResponseChange(next);
      setSyncNotice(
        next === 'accepted'
          ? 'AutoSync bestätigt Termine jetzt automatisch.'
          : 'AutoSync sendet keine automatische Antwort mehr.',
      );
    } catch (error) {
      setSyncError('AutoSync-Einstellung konnte nicht gespeichert werden.');
    } finally {
      setBusy(false);
    }
  }

  async function handleResponse(event: TrackedEvent, response: TrackedEvent['response_status']) {
    if (respondingId !== null) {
      return;
    }
    if (event.response_status === response) {
      return;
    }
    setRespondingId(event.id);
    setSyncError(null);
    setSyncResult([]);
    setMissing([]);
    try {
      const updated = await onRespondToEvent(event.id, response);
      const title = updated.summary ?? updated.uid;
      if (response === 'none') {
        setSyncNotice(`Antwort für "${title}" wurde zurückgesetzt.`);
      } else {
        const label = responseLabelMap[response];
        setSyncNotice(`Antwort für "${title}" wurde auf ${label} gesetzt.`);
      }
    } catch (error) {
      setSyncError('Teilnahmestatus konnte nicht gespeichert werden.');
    } finally {
      setRespondingId(null);
    }
  }

  const showInitialLoading = loading && events.length === 0;
  const showEmptyState = !loading && filteredEvents.length === 0;

  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
          <p className="text-xs uppercase tracking-wide text-slate-500">Ausstehend</p>
          <p className="mt-1 text-2xl font-semibold text-slate-100">{metrics.outstanding}</p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
          <p className="text-xs uppercase tracking-wide text-slate-500">Verarbeitet</p>
          <p className="mt-1 text-2xl font-semibold text-emerald-400">{metrics.processed}</p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
          <p className="text-xs uppercase tracking-wide text-slate-500">Abgesagt</p>
          <p className="mt-1 text-2xl font-semibold text-rose-300">{metrics.cancelled}</p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
          <p className="text-xs uppercase tracking-wide text-slate-500">Antwort offen</p>
          <p className="mt-1 text-2xl font-semibold text-amber-300">{metrics.awaitingDecision}</p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
          <p className="text-xs uppercase tracking-wide text-slate-500">Heute</p>
          <p className="mt-1 text-2xl font-semibold text-sky-300">{metrics.today}</p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
          <p className="text-xs uppercase tracking-wide text-slate-500">Konflikte</p>
          <p className="mt-1 text-2xl font-semibold text-amber-300">{metrics.conflicts}</p>
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 shadow-lg shadow-emerald-500/5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={handleScan}
              disabled={busy}
              className="rounded-lg bg-slate-800 px-4 py-2 text-sm font-semibold text-slate-100 transition hover:bg-slate-700 disabled:opacity-40"
            >
              Postfächer scannen
            </button>
            <button
              onClick={handleSyncAll}
              disabled={busy}
              className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-semibold text-sky-950 transition hover:bg-sky-500 disabled:opacity-40"
            >
              Alle synchronisieren
            </button>
            <button
              onClick={handleAutoSyncToggle}
              disabled={busy}
              className={`rounded-lg px-4 py-2 text-sm font-semibold transition disabled:opacity-40 ${
                autoSyncEnabled
                  ? 'bg-emerald-500 text-emerald-950 hover:bg-emerald-400'
                  : 'bg-slate-800 text-slate-100 hover:bg-slate-700'
              }`}
            >
              {autoSyncEnabled ? 'AutoSync deaktivieren' : 'AutoSync aktivieren'}
            </button>
            <button
              onClick={handleSyncSelection}
              disabled={selected.length === 0 || busy}
              className="rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-emerald-950 transition hover:bg-emerald-400 disabled:opacity-50"
            >
              Auswahl synchronisieren ({selected.length})
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-4">
            <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-300">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-slate-600 bg-slate-950"
                checked={autoSyncResponse === 'accepted'}
                onChange={handleAutoResponseToggle}
                disabled={busy}
              />
              <span>AutoSync sagt Termine automatisch zu</span>
            </label>
            <div className="relative">
              <input
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
                className="w-64 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-emerald-400 focus:outline-none"
                placeholder="Termine suchen…"
              />
            </div>
          </div>
        </div>
      </div>

      {syncError && (
        <div className="rounded-lg border border-rose-700 bg-rose-500/10 p-4 text-sm text-rose-200">
          <p className="font-semibold">{syncError}</p>
          {missing.length > 0 && (
            <ul className="mt-2 space-y-1 text-xs">
              {missing.map((item, index) => (
                <li key={`${item.uid ?? index}-${index}`}>
                  <span className="font-semibold">{item.uid ?? 'Unbekannte UID'}:</span>{' '}
                  {item.reason ?? 'Keine Zuordnung gefunden'}
                  {(item.account_id || item.folder) && (
                    <span className="text-slate-300">{` (Konto ${
                      item.account_id ?? 'unbekannt'
                    }${item.folder ? ` · ${item.folder}` : ''})`}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {syncNotice && (
        <div className="rounded-lg border border-emerald-700 bg-emerald-500/10 p-4 text-sm text-emerald-200">
          <p className="font-semibold">{syncNotice}</p>
          {syncResult.length > 0 && (
            <div className="mt-2">
              <p>Folgende UIDs wurden exportiert:</p>
              <ul className="mt-1 list-inside list-disc text-xs">
                {syncResult.map((uid) => (
                  <li key={uid}>{uid}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {showInitialLoading && (
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-6 text-sm text-slate-300">
          Lade Termine …
        </div>
      )}

      {showEmptyState && (
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-6 text-sm text-slate-300">
          Keine Termine gefunden.
        </div>
      )}

      {!showInitialLoading && filteredEvents.length > 0 && (
        <div className="space-y-3">
          {filteredEvents.map((event) => {
            const isOpen = openItems.includes(event.id);
            const dateRange = formatDateRange(event);
            const sourceParts = [
              event.source_account_id ? `Konto #${event.source_account_id}` : null,
              event.source_folder,
            ].filter(Boolean);
            const conflictCount = event.conflicts?.length ?? 0;
            return (
              <div
                key={event.id}
                className="overflow-hidden rounded-xl border border-slate-800 bg-slate-950 shadow-sm shadow-slate-900/40"
              >
                <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start sm:justify-between">
                  <div className="flex flex-1 items-start gap-3">
                    <input
                      type="checkbox"
                      className="mt-1 h-4 w-4 rounded border-slate-600 bg-slate-950"
                      checked={selected.includes(event.id)}
                      onChange={() => toggleSelection(event.id)}
                    />
                    <button
                      type="button"
                      onClick={() => toggleOpen(event.id)}
                      className="mt-0.5 flex h-6 w-6 items-center justify-center rounded-full border border-slate-700 text-slate-300 transition hover:border-slate-500 hover:text-slate-100"
                      aria-label={isOpen ? 'Details schließen' : 'Details anzeigen'}
                    >
                      <span className={`text-lg transition-transform ${isOpen ? 'rotate-180' : ''}`}>
                        ▾
                      </span>
                    </button>
                    <div className="space-y-2">
                      <div className="text-sm font-semibold text-slate-100">
                        {event.summary ?? 'Unbenannter Termin'}
                      </div>
                      <p className="text-xs text-slate-400">{dateRange}</p>
                      <p className="text-xs text-slate-500">
                        {sourceParts.length > 0 ? sourceParts.join(' · ') : 'Quelle unbekannt'}
                      </p>
                    </div>
                  </div>
                  <div className="flex flex-col items-start gap-2 sm:items-end">
                    <span
                      className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${
                        statusStyleMap[event.status]
                      }`}
                    >
                      {statusLabelMap[event.status]}
                    </span>
                    <span
                      className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${
                        responseStyleMap[event.response_status]
                      }`}
                    >
                      {responseLabelMap[event.response_status]}
                    </span>
                    {conflictCount > 0 && (
                      <span className="inline-flex items-center rounded-full bg-amber-500/20 px-3 py-1 text-xs font-semibold text-amber-300">
                        {conflictCount === 1 ? '1 Konflikt' : `${conflictCount} Konflikte`}
                      </span>
                    )}
                  </div>
                </div>
                {isOpen && (
                  <div className="border-t border-slate-800 bg-slate-900/70 px-4 py-4 text-sm text-slate-200">
                    <div className="grid gap-3 sm:grid-cols-2">
                      <div>
                        <p className="text-xs uppercase tracking-wide text-slate-500">Organisator</p>
                        <p className="mt-1 text-slate-200">{event.organizer ?? 'Keine Angabe'}</p>
                      </div>
                      <div>
                        <p className="text-xs uppercase tracking-wide text-slate-500">UID</p>
                        <p className="mt-1 break-all text-slate-300">{event.uid}</p>
                      </div>
                      <div>
                        <p className="text-xs uppercase tracking-wide text-slate-500">Quelle</p>
                        <p className="mt-1 text-slate-300">
                          {sourceParts.length > 0 ? sourceParts.join(' · ') : 'Keine Zuordnung'}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs uppercase tracking-wide text-slate-500">Zeitspanne</p>
                        <p className="mt-1 text-slate-300">{dateRange}</p>
                      </div>
                    </div>
                    {conflictCount > 0 && (
                      <div className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-100">
                        <p className="text-sm font-semibold text-amber-200">Terminkonflikte erkannt</p>
                        <p className="mt-1 text-amber-100/80">
                          In den verknüpften CalDAV-Daten überschneiden sich folgende Termine mit diesem Eintrag:
                        </p>
                        <ul className="mt-2 space-y-1">
                          {event.conflicts.map((conflict) => (
                            <li key={conflict.uid} className="leading-snug">
                              <span className="font-semibold text-amber-200">
                                {conflict.summary ?? conflict.uid}
                              </span>
                              <span className="block text-[11px] text-amber-100/70">
                                {formatConflictRange(conflict)}
                              </span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    <div className="mt-4">
                      <p className="text-xs uppercase tracking-wide text-slate-500">Historie</p>
                      {event.history.length > 0 ? (
                        <ul className="mt-2 space-y-1 text-xs text-slate-300">
                          {event.history.map((entry, index) => (
                            <li key={`${entry.timestamp}-${index}`}>
                              <span className="font-semibold text-slate-200">
                                {new Date(entry.timestamp).toLocaleString()}:
                              </span>{' '}
                              {entry.description}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="mt-2 text-xs text-slate-400">Keine Historie vorhanden.</p>
                      )}
                    </div>
                    <div className="mt-4 flex flex-wrap gap-2">
                      {responseActions.map((action) => (
                        <button
                          key={action.value}
                          type="button"
                          onClick={() => handleResponse(event, action.value)}
                          disabled={respondingId === event.id}
                          className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition disabled:opacity-60 ${
                            action.className
                          } ${
                            event.response_status === action.value
                              ? 'ring-2 ring-emerald-300/60 ring-offset-2 ring-offset-slate-900'
                              : ''
                          }`}
                        >
                          {action.label}
                        </button>
                      ))}
                      <button
                        type="button"
                        onClick={() => handleResponse(event, 'none')}
                        disabled={respondingId === event.id}
                        className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs font-semibold text-slate-200 transition hover:border-slate-500 hover:text-slate-100 disabled:opacity-60"
                      >
                        Antwort zurücksetzen
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
