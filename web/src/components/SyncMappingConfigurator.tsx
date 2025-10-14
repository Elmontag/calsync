import { FormEvent, useEffect, useMemo, useState } from 'react';
import {
  Account,
  CalendarInfo,
  SyncMapping,
  SyncMappingCreateInput,
} from '../types/api';
import { fetchCalendars } from '../api/hooks';

interface Props {
  accounts: Account[];
  mappings: SyncMapping[];
  onCreate: (payload: SyncMappingCreateInput) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
}

const emptyForm: SyncMappingCreateInput = {
  imap_account_id: 0,
  imap_folder: '',
  caldav_account_id: 0,
  calendar_url: '',
  calendar_name: '',
};

export default function SyncMappingConfigurator({ accounts, mappings, onCreate, onDelete }: Props) {
  const [form, setForm] = useState<SyncMappingCreateInput>(emptyForm);
  const [calendars, setCalendars] = useState<CalendarInfo[]>([]);
  const [loadingCalendars, setLoadingCalendars] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const imapAccounts = useMemo(
    () => accounts.filter((account) => account.type === 'imap'),
    [accounts],
  );
  const caldavAccounts = useMemo(
    () => accounts.filter((account) => account.type === 'caldav'),
    [accounts],
  );

  useEffect(() => {
    if (!form.caldav_account_id) {
      setCalendars([]);
      return;
    }
    async function loadCalendars() {
      try {
        setLoadingCalendars(true);
        const data = await fetchCalendars(form.caldav_account_id);
        setCalendars(data);
        setError(null);
      } catch (err) {
        setError('Konnte Kalender nicht laden.');
        setCalendars([]);
      } finally {
        setLoadingCalendars(false);
      }
    }
    loadCalendars();
  }, [form.caldav_account_id]);

  useEffect(() => {
    if (form.imap_account_id === 0 && imapAccounts.length > 0) {
      setForm((prev) => ({ ...prev, imap_account_id: imapAccounts[0].id }));
    }
  }, [imapAccounts, form.imap_account_id]);

  useEffect(() => {
    if (form.caldav_account_id === 0 && caldavAccounts.length > 0) {
      setForm((prev) => ({ ...prev, caldav_account_id: caldavAccounts[0].id }));
    }
  }, [caldavAccounts, form.caldav_account_id]);

  const selectedImapAccount = imapAccounts.find((account) => account.id === form.imap_account_id);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!form.imap_account_id || !form.imap_folder || !form.caldav_account_id || !form.calendar_url) {
      setError('Bitte alle Felder ausfüllen.');
      return;
    }
    setError(null);
    await onCreate(form);
    setForm((prev) => ({ ...prev, calendar_url: '', calendar_name: '' }));
  }

  function resolveAccountLabel(id: number) {
    return accounts.find((account) => account.id === id)?.label ?? `Konto ${id}`;
  }

  return (
    <div className="space-y-6 rounded-xl border border-slate-800 bg-slate-900 p-6">
      <div>
        <h2 className="text-lg font-semibold text-slate-100">Sync-Zuordnungen verwalten</h2>
        <p className="text-sm text-slate-400">
          Definiere hier, welcher IMAP-Ordner in welchen CalDAV-Kalender exportiert wird. Die Einstellungen
          gelten sowohl für manuelle Exporte als auch für AutoSync.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wide text-slate-400">
              IMAP Konto
            </label>
            <select
              value={form.imap_account_id}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, imap_account_id: Number(event.target.value), imap_folder: '' }))
              }
              className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-2 text-slate-100"
            >
              {imapAccounts.length === 0 && <option>Kein IMAP Konto verfügbar</option>}
              {imapAccounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wide text-slate-400">Ordner</label>
            <select
              value={form.imap_folder}
              onChange={(event) => setForm((prev) => ({ ...prev, imap_folder: event.target.value }))}
              className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-2 text-slate-100"
            >
              <option value="">Bitte Ordner wählen</option>
              {selectedImapAccount?.imap_folders.map((folder) => (
                <option key={folder.name} value={folder.name}>
                  {folder.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wide text-slate-400">
              CalDAV Konto
            </label>
            <select
              value={form.caldav_account_id}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, caldav_account_id: Number(event.target.value), calendar_url: '' }))
              }
              className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-2 text-slate-100"
            >
              {caldavAccounts.length === 0 && <option>Kein CalDAV Konto verfügbar</option>}
              {caldavAccounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wide text-slate-400">
              Zielkalender
            </label>
            <select
              value={form.calendar_url}
              onChange={(event) => setForm((prev) => ({ ...prev, calendar_url: event.target.value }))}
              disabled={loadingCalendars || calendars.length === 0}
              className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-2 text-slate-100 disabled:opacity-50"
            >
              <option value="">Kalender wählen</option>
              {calendars.map((calendar) => (
                <option key={calendar.url} value={calendar.url}>
                  {calendar.name}
                </option>
              ))}
            </select>
            {loadingCalendars && (
              <p className="mt-1 text-xs text-slate-400">Lade verfügbare Kalender…</p>
            )}
            {!loadingCalendars && calendars.length === 0 && (
              <p className="mt-1 text-xs text-slate-500">Keine Kalender gefunden.</p>
            )}
          </div>
        </div>

        <div>
          <label className="block text-xs font-semibold uppercase tracking-wide text-slate-400">
            Anzeigename (optional)
          </label>
          <input
            value={form.calendar_name ?? ''}
            onChange={(event) => setForm((prev) => ({ ...prev, calendar_name: event.target.value }))}
            className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-2 text-slate-100"
            placeholder="Teamkalender"
          />
        </div>

        {error && <p className="text-sm text-rose-300">{error}</p>}

        <button
          type="submit"
          className="w-full rounded-lg bg-emerald-500 py-2 text-sm font-semibold text-emerald-950 transition hover:bg-emerald-400"
        >
          Zuordnung speichern
        </button>
      </form>

      <div className="space-y-3">
        {mappings.length === 0 ? (
          <p className="text-sm text-slate-400">Noch keine Zuordnungen konfiguriert.</p>
        ) : (
          mappings.map((mapping) => (
            <div
              key={mapping.id}
              className="flex items-start justify-between rounded-lg border border-slate-800 bg-slate-950 p-4"
            >
              <div className="text-sm text-slate-200">
                <p className="font-semibold">{resolveAccountLabel(mapping.imap_account_id)}</p>
                <p className="text-slate-400">Ordner: {mapping.imap_folder}</p>
                <p className="text-slate-400">
                  ➜ {resolveAccountLabel(mapping.caldav_account_id)}{' '}
                  {mapping.calendar_name ? `(${mapping.calendar_name})` : mapping.calendar_url}
                </p>
              </div>
              <button
                onClick={() => onDelete(mapping.id)}
                className="rounded bg-rose-900 px-3 py-1 text-xs font-semibold text-rose-100 hover:bg-rose-800"
              >
                Entfernen
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
