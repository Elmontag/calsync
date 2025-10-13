import { useForm, useFieldArray } from 'react-hook-form';
import { AccountCreateInput } from '../types/api';

interface Props {
  onSubmit: (data: AccountCreateInput) => Promise<void>;
}

const defaultFolder = { name: 'INBOX', include_subfolders: true };

export default function AccountForm({ onSubmit }: Props) {
  const { register, control, handleSubmit, watch, reset } = useForm<AccountCreateInput>({
    defaultValues: {
      label: '',
      type: 'imap',
      direction: 'imap_to_caldav',
      settings: {},
      imap_folders: [defaultFolder],
    },
  });
  const { fields, append, remove } = useFieldArray({ control, name: 'imap_folders' });
  const accountType = watch('type');

  const submit = handleSubmit(async (values) => {
    const payload: AccountCreateInput = {
      ...values,
      settings: accountType === 'imap'
        ? {
            host: (values.settings as any).host,
            username: (values.settings as any).username,
            password: (values.settings as any).password,
            port: (values.settings as any).port ? Number((values.settings as any).port) : undefined,
            ssl: (values.settings as any).ssl ?? true,
          }
        : {
            url: (values.settings as any).url,
            username: (values.settings as any).username,
            password: (values.settings as any).password,
          },
    };
    await onSubmit(payload);
    reset();
  });

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

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-slate-200">Kontotyp</label>
          <select
            {...register('type')}
            className="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 p-2"
          >
            <option value="imap">IMAP</option>
            <option value="caldav">CalDAV</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-200">Richtung</label>
          <select
            {...register('direction')}
            className="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 p-2"
          >
            <option value="imap_to_caldav">IMAP ➜ CalDAV</option>
            <option value="bidirectional">Bidirektional</option>
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
                onClick={() => append(defaultFolder)}
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

      <button
        type="submit"
        className="w-full rounded-lg bg-emerald-500 py-2 text-sm font-semibold text-emerald-950 transition hover:bg-emerald-400"
      >
        Konto speichern
      </button>
    </form>
  );
}
