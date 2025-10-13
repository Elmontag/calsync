import { Fragment, useState } from 'react';
import { ManualSyncRequest, TrackedEvent } from '../types/api';
import { Dialog, Transition } from '@headlessui/react';

interface Props {
  events: TrackedEvent[];
  onManualSync: (payload: ManualSyncRequest) => Promise<{ uploaded: string[] }>;
  onScan: () => Promise<void>;
}

export default function EventTable({ events, onManualSync, onScan }: Props) {
  const [selected, setSelected] = useState<number[]>([]);
  const [calendarUrl, setCalendarUrl] = useState('');
  const [open, setOpen] = useState(false);
  const [syncResult, setSyncResult] = useState<string[]>([]);

  function toggleSelection(id: number) {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id],
    );
  }

  async function handleSync() {
    const payload: ManualSyncRequest = {
      event_ids: selected,
      target_calendar: calendarUrl,
    };
    const result = await onManualSync(payload);
    setSyncResult(result.uploaded);
    setOpen(false);
    setSelected([]);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-100">Gefundene Termine</h2>
        <div className="space-x-2">
          <button
            onClick={onScan}
            className="rounded-lg bg-slate-800 px-4 py-2 text-sm font-semibold text-slate-100 hover:bg-slate-700"
          >
            Postfächer scannen
          </button>
          <button
            onClick={() => setOpen(true)}
            disabled={selected.length === 0}
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

      <Transition appear show={open} as={Fragment}>
        <Dialog as="div" className="relative z-10" onClose={() => setOpen(false)}>
          <Transition.Child
            as={Fragment}
            enter="ease-out duration-300"
            enterFrom="opacity-0"
            enterTo="opacity-100"
            leave="ease-in duration-200"
            leaveFrom="opacity-100"
            leaveTo="opacity-0"
          >
            <div className="fixed inset-0 bg-slate-950/70" />
          </Transition.Child>

          <div className="fixed inset-0 overflow-y-auto">
            <div className="flex min-h-full items-center justify-center p-4 text-center">
              <Transition.Child
                as={Fragment}
                enter="ease-out duration-300"
                enterFrom="opacity-0 scale-95"
                enterTo="opacity-100 scale-100"
                leave="ease-in duration-200"
                leaveFrom="opacity-100 scale-100"
                leaveTo="opacity-0 scale-95"
              >
                <Dialog.Panel className="w-full max-w-lg transform overflow-hidden rounded-2xl bg-slate-900 p-6 text-left align-middle shadow-xl transition-all">
                  <Dialog.Title className="text-lg font-medium text-slate-100">
                    Zielkalender wählen
                  </Dialog.Title>
                  <div className="mt-4 space-y-2">
                    <label className="text-sm text-slate-300">CalDAV Kalender URL</label>
                    <input
                      value={calendarUrl}
                      onChange={(event) => setCalendarUrl(event.target.value)}
                      className="w-full rounded border border-slate-700 bg-slate-950 p-2 text-slate-100"
                      placeholder="https://cloud.example.com/remote.php/dav/calendars/user/persoenlich/"
                    />
                  </div>
                  <div className="mt-6 flex justify-end gap-2">
                    <button
                      type="button"
                      className="rounded-lg bg-slate-800 px-4 py-2 text-sm text-slate-200 hover:bg-slate-700"
                      onClick={() => setOpen(false)}
                    >
                      Abbrechen
                    </button>
                    <button
                      type="button"
                      disabled={!calendarUrl}
                      className="rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-emerald-950 hover:bg-emerald-400 disabled:opacity-40"
                      onClick={handleSync}
                    >
                      Jetzt exportieren
                    </button>
                  </div>
                </Dialog.Panel>
              </Transition.Child>
            </div>
          </div>
        </Dialog>
      </Transition>

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
