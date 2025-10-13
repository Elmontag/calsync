import { useState } from 'react';
import { ManualSyncRequest, TrackedEvent } from '../types/api';

interface Props {
  events: TrackedEvent[];
  onManualSync: (payload: ManualSyncRequest) => Promise<{ uploaded: string[] }>;
  onScan: () => Promise<void>;
  onSyncAll: () => Promise<void>;
  autoSyncEnabled: boolean;
  onAutoSyncToggle: (enabled: boolean) => Promise<void>;
}

export default function EventTable({
  events,
  onManualSync,
  onScan,
  onSyncAll,
  autoSyncEnabled,
  onAutoSyncToggle,
}: Props) {
  const [selected, setSelected] = useState<number[]>([]);
  const [syncResult, setSyncResult] = useState<string[]>([]);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [missing, setMissing] = useState<
    Array<{ uid?: string; reason?: string; account_id?: number; folder?: string }>
  >([]);
  const [busy, setBusy] = useState(false);

  function toggleSelection(id: number) {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id],
    );
  }

  async function handleSyncSelection() {
    if (selected.length === 0) {
      return;
    }
    setBusy(true);
    setSyncError(null);
    setMissing([]);
    try {
      const payload: ManualSyncRequest = { event_ids: selected };
      const result = await onManualSync(payload);
      setSyncResult(result.uploaded);
      setSelected([]);
    } catch (error: any) {
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
            })),
          );
        }
      } else {
        setSyncError('Synchronisation fehlgeschlagen.');
      }
      setSyncResult([]);
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

  async function handleAutoSyncToggle() {
    setBusy(true);
    try {
      await onAutoSyncToggle(!autoSyncEnabled);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-100">Gefundene Termine</h2>
          <p className="text-sm text-slate-400">
            Wähle Termine aus oder synchronisiere alle automatisch über die Zuordnungen.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={onScan}
            className="rounded-lg bg-slate-800 px-4 py-2 text-sm font-semibold text-slate-100 hover:bg-slate-700"
          >
            Postfächer scannen
          </button>
          <button
            onClick={handleSyncAll}
            disabled={busy}
            className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-semibold text-sky-950 hover:bg-sky-500 disabled:opacity-40"
          >
            Alle synchronisieren
          </button>
          <button
            onClick={handleAutoSyncToggle}
            disabled={busy}
            className={`rounded-lg px-4 py-2 text-sm font-semibold transition ${
              autoSyncEnabled
                ? 'bg-emerald-500 text-emerald-950 hover:bg-emerald-400'
                : 'bg-slate-800 text-slate-100 hover:bg-slate-700'
            } disabled:opacity-40`}
          >
            {autoSyncEnabled ? 'AutoSync deaktivieren' : 'AutoSync aktivieren'}
          </button>
          <button
            onClick={handleSyncSelection}
            disabled={selected.length === 0 || busy}
            className="rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-emerald-950 hover:bg-emerald-400 disabled:opacity-50"
          >
            Auswahl synchronisieren
          </button>
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-slate-800">
        <table className="min-w-full divide-y divide-slate-800">
          <thead className="bg-slate-900">
            <tr>
              <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-400">
                Auswahl
              </th>
              <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-400">
                Betreff
              </th>
              <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-400">
                Quelle
              </th>
              <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-400">
                Zeitraum
              </th>
              <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-400">
                Status
              </th>
              <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-400">
                Verlauf
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-900 bg-slate-950">
            {events.map((event) => (
              <tr key={event.id} className="hover:bg-slate-900">
                <td className="px-4 py-2">
                  <input
                    type="checkbox"
                    checked={selected.includes(event.id)}
                    onChange={() => toggleSelection(event.id)}
                  />
                </td>
                <td className="px-4 py-2">
                  <p className="text-sm font-medium text-slate-100">{event.summary ?? 'Unbenannt'}</p>
                  <p className="text-xs text-slate-400">UID: {event.uid}</p>
                </td>
                <td className="px-4 py-2 text-xs text-slate-300">
                  {event.source_account_id ? `Konto #${event.source_account_id}` : 'unbekannt'}
                  {event.source_folder ? ` · ${event.source_folder}` : ''}
                </td>
                <td className="px-4 py-2 text-sm text-slate-300">
                  {event.start ? new Date(event.start).toLocaleString() : 'Unbekannt'}
                  {event.end ? ` – ${new Date(event.end).toLocaleString()}` : ''}
                </td>
                <td className="px-4 py-2 text-sm">
                  <span
                    className={`inline-flex rounded-full px-2 py-1 text-xs font-semibold ${
                      event.status === 'synced'
                        ? 'bg-emerald-500/10 text-emerald-300'
                        : event.status === 'cancelled'
                        ? 'bg-rose-500/10 text-rose-300'
                        : 'bg-sky-500/10 text-sky-300'
                    }`}
                  >
                    {event.status}
                  </span>
                </td>
                <td className="px-4 py-2 text-xs text-slate-300">
                  <ul className="space-y-1">
                    {event.history.map((entry, index) => (
                      <li key={index}>
                        <span className="font-semibold text-slate-200">
                          {new Date(entry.timestamp).toLocaleString()}:
                        </span>{' '}
                        {entry.description}
                      </li>
                    ))}
                  </ul>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
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

      {syncResult.length > 0 && (
        <div className="rounded-lg border border-emerald-700 bg-emerald-500/10 p-4 text-sm text-emerald-200">
          <p className="font-semibold">Erfolg!</p>
          <p className="mt-1">Folgende UIDs wurden exportiert:</p>
          <ul className="mt-1 list-inside list-disc">
            {syncResult.map((uid) => (
              <li key={uid}>{uid}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
