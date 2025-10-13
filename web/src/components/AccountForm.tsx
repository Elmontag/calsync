import { useEffect, useState } from 'react';
import { useForm, useFieldArray } from 'react-hook-form';
import { runConnectionTest } from '../api/hooks';
import { Account, AccountCreateInput, ConnectionTestResult } from '../types/api';

interface Props {
  account?: Account | null;
  onSubmit: (data: AccountCreateInput) => Promise<void>;
  onCancel?: () => void;
  loading?: boolean;
}

const createDefaultFolder = () => ({ name: 'INBOX', include_subfolders: true });

function toFormDefaults(account?: Account | null): AccountCreateInput {
  if (!account) {
    return {
      label: '',
      type: 'imap',
      settings: { ssl: true },
      imap_folders: [createDefaultFolder()],
    };
  }

  if (account.type === 'imap') {
    const settings = account.settings as Record<string, any>;
    return {
      label: account.label,
      type: 'imap',
      settings: {
        host: settings.host ?? '',
        username: settings.username ?? '',
        password: settings.password ?? '',
        port: settings.port ?? '',
        ssl: settings.ssl ?? true,
      },
      imap_folders:
        account.imap_folders.length > 0
          ? account.imap_folders.map((folder) => ({
              name: folder.name,
              include_subfolders: folder.include_subfolders,
            }))
          : [createDefaultFolder()],
    };
  }

  const settings = account.settings as Record<string, any>;
  return {
    label: account.label,
    type: 'caldav',
    settings: {
      url: settings.url ?? '',
      username: settings.username ?? '',
      password: settings.password ?? '',
    },
    imap_folders: [],
  };
}

export default function AccountForm({ account, onSubmit, onCancel, loading }: Props) {
  const defaultValues = toFormDefaults(account);
  const { register, control, handleSubmit, watch, reset, getValues } = useForm<AccountCreateInput>({
    defaultValues,
  });
  const { fields, append, remove } = useFieldArray({ control, name: 'imap_folders' });
  const accountType = watch('type');
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    reset(toFormDefaults(account));
    setTestResult(null);
  }, [account, reset]);

  useEffect(() => {
    if (accountType === 'imap' && fields.length === 0) {
      append(createDefaultFolder());
    }
  }, [accountType, fields.length, append]);

  useEffect(() => {
    setTestResult(null);
  }, [accountType]);

  const submit = handleSubmit(async (values) => {
    const payload = buildAccountPayload(values);
    await onSubmit(payload);
    if (!account) {
      reset(toFormDefaults());
    }
    setTestResult(null);
  });

  function buildAccountPayload(values: AccountCreateInput): AccountCreateInput {
    if (values.type === 'imap') {
      const settings = values.settings as Record<string, unknown>;
      return {
        ...values,
        settings: {
          host: settings.host,
          username: settings.username,
          password: settings.password,
          port: settings.port ? Number(settings.port) : undefined,
          ssl: settings.ssl ?? true,
        },
      };
    }

    const settings = values.settings as Record<string, unknown>;
    return {
      ...values,
      settings: {
        url: settings.url,
        username: settings.username,
        password: settings.password,
      },
      imap_folders: [],
    };
  }

  async function handleConnectionTest() {
    const values = getValues();
    const payload = buildAccountPayload(values);
    setTesting(true);
    try {
      const requestSettings =
        payload.type === 'imap'
          ? {
              ...(payload.settings as Record<string, unknown>),
              folders: payload.imap_folders.map((folder) => folder.name),
            }
          : (payload.settings as Record<string, unknown>);
      const result = await runConnectionTest({
        type: payload.type,
        settings: requestSettings,
      });
      setTestResult(result);
    } catch (error) {
      setTestResult({ success: false, message: 'Verbindungstest fehlgeschlagen.' });
    } finally {
      setTesting(false);
    }
  }

  return (
    <form className="space-y-6" onSubmit={submit}>
      <div>
        <label className="block text-sm font-medium text-slate-200">Bezeichnung</label>
        <input
          {...register('label', { required: true })}
          className="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 p-2 text-slate-100 focus:border-emerald-400 focus:outline-none"
          placeholder="Mein IMAP Konto"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="sm:col-span-1">
          <label className="block text-sm font-medium text-slate-200">Kontotyp</label>
          <select
            {...register('type')}
            className="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 p-2"
          >
            <option value="imap">IMAP</option>
            <option value="caldav">CalDAV</option>
          </select>
        </div>
      </div>

      {accountType === 'imap' ? (
        <div className="space-y-4 rounded-lg border border-slate-800 bg-slate-900 p-4">
          <h3 className="text-sm font-semibold text-slate-300">IMAP Einstellungen</h3>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs uppercase tracking-wide text-slate-400">Host</label>
              <input
                {...register('settings.host', { required: true })}
                className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-2"
              />
            </div>
            <div>
              <label className="block text-xs uppercase tracking-wide text-slate-400">Port</label>
              <input
                {...register('settings.port')}
                className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-2"
                type="number"
              />
            </div>
            <div>
              <label className="block text-xs uppercase tracking-wide text-slate-400">Benutzername</label>
              <input
                {...register('settings.username', { required: true })}
                className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-2"
              />
            </div>
            <div>
              <label className="block text-xs uppercase tracking-wide text-slate-400">Passwort</label>
              <input
                {...register('settings.password', { required: true })}
                className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-2"
                type="password"
              />
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                Zu überwachende Ordner
              </h4>
              <button
                type="button"
                onClick={() => append(createDefaultFolder())}
                className="text-xs font-medium text-emerald-400 hover:text-emerald-300"
              >
                Ordner hinzufügen
              </button>
            </div>
            <div className="mt-2 space-y-2">
              {fields.map((field, index) => (
                <div key={field.id} className="flex gap-2">
                  <input
                    {...register(`imap_folders.${index}.name` as const, { required: true })}
                    className="flex-1 rounded border border-slate-700 bg-slate-950 p-2"
                    placeholder="INBOX/Calendar"
                  />
                  <label className="flex items-center gap-2 rounded border border-slate-700 bg-slate-950 px-3">
                    <input
                      type="checkbox"
                      {...register(`imap_folders.${index}.include_subfolders` as const)}
                    />
                    <span className="text-xs text-slate-300">inkl. Unterordner</span>
                  </label>
                  <button
                    type="button"
                    onClick={() => remove(index)}
                    className="rounded bg-rose-900 px-3 text-xs font-semibold text-rose-200 hover:bg-rose-800"
                  >
                    Entfernen
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div className="space-y-4 rounded-lg border border-slate-800 bg-slate-900 p-4">
          <h3 className="text-sm font-semibold text-slate-300">CalDAV Einstellungen</h3>
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2">
              <label className="block text-xs uppercase tracking-wide text-slate-400">URL</label>
              <input
                {...register('settings.url', { required: true })}
                className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-2"
                placeholder="https://cloud.example.com/remote.php/dav/calendars/user/persoenlich/"
              />
            </div>
            <div>
              <label className="block text-xs uppercase tracking-wide text-slate-400">Benutzername</label>
              <input
                {...register('settings.username')}
                className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-2"
              />
            </div>
            <div>
              <label className="block text-xs uppercase tracking-wide text-slate-400">Passwort</label>
              <input
                {...register('settings.password')}
                className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-2"
                type="password"
              />
            </div>
          </div>
        </div>
      )}

      <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h3 className="text-sm font-semibold text-slate-200">Verbindungstest</h3>
            <p className="text-xs text-slate-400">
              Nutze die aktuellen Eingaben, um Zugangsdaten direkt zu prüfen.
            </p>
          </div>
          <button
            type="button"
            onClick={handleConnectionTest}
            disabled={testing}
            className="rounded-lg bg-slate-800 px-4 py-2 text-xs font-semibold text-slate-100 transition hover:bg-slate-700 disabled:opacity-50"
          >
            {testing ? 'Teste…' : 'Verbindung testen'}
          </button>
        </div>
        {testResult && (
          <div
            className={`mt-3 rounded border px-3 py-2 text-xs ${
              testResult.success
                ? 'border-emerald-600 text-emerald-200'
                : 'border-rose-600 text-rose-200'
            }`}
          >
            <p className="font-semibold">{testResult.message}</p>
            {testResult.details && (
              <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap text-[11px] text-slate-200/90">
                {JSON.stringify(testResult.details, null, 2)}
              </pre>
            )}
          </div>
        )}
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-end">
        {account && (
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-slate-700 px-4 py-2 text-sm font-semibold text-slate-200 hover:border-slate-600 hover:text-slate-100"
          >
            Abbrechen
          </button>
        )}
        <button
          type="submit"
          disabled={loading}
          className="w-full rounded-lg bg-emerald-500 py-2 text-sm font-semibold text-emerald-950 transition hover:bg-emerald-400 disabled:opacity-50 sm:w-auto sm:px-6"
        >
          {loading ? 'Speichere…' : account ? 'Konto aktualisieren' : 'Konto speichern'}
        </button>
      </div>
    </form>
  );
}
