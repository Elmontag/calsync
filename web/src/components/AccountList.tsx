import { Account, ConnectionTestResult } from '../types/api';

interface Props {
  accounts: Account[];
  onEdit: (account: Account) => void;
  onDelete: (account: Account) => void;
  onTest: (account: Account) => void;
  activeAccountId?: number | null;
  testingAccountId?: number | null;
  testResults?: Record<number, ConnectionTestResult>;
}

export default function AccountList({
  accounts,
  onEdit,
  onDelete,
  onTest,
  activeAccountId,
  testingAccountId,
  testResults = {},
}: Props) {
  if (accounts.length === 0) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-6 text-sm text-slate-400">
        Noch keine Konten hinterlegt.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {accounts.map((account) => (
        <div
          key={account.id}
          className={`rounded-xl border bg-slate-900 p-5 transition ${
            activeAccountId === account.id
              ? 'border-emerald-500/60 shadow-lg shadow-emerald-500/10'
              : 'border-slate-800'
          }`}
        >
          <div className="flex items-start justify-between">
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-base font-semibold text-slate-100">{account.label}</h3>
                {activeAccountId === account.id && (
                  <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-300">
                    in Bearbeitung
                  </span>
                )}
              </div>
              <p className="text-xs uppercase tracking-wide text-slate-500">
                {account.type === 'imap' ? 'IMAP' : 'CalDAV'} ·{' '}
                {account.direction === 'imap_to_caldav' ? 'IMAP ➜ CalDAV' : 'Bidirektional'}
              </p>
            </div>
            {account.type === 'imap' && (
              <span className="rounded-full bg-slate-800 px-3 py-1 text-xs text-slate-300">
                {account.imap_folders.length} Ordner
              </span>
            )}
          </div>
          {account.type === 'imap' && account.imap_folders.length > 0 && (
            <ul className="mt-3 space-y-1 text-sm text-slate-300">
              {account.imap_folders.map((folder) => (
                <li key={folder.name}>
                  {folder.name}
                  {folder.include_subfolders ? ' (inkl. Unterordner)' : ''}
                </li>
              ))}
            </ul>
          )}
          <div className="mt-4 flex flex-wrap gap-2">
            <button
              onClick={() => onEdit(account)}
              className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs font-semibold text-slate-200 transition hover:border-slate-600 hover:text-slate-100"
            >
              Bearbeiten
            </button>
            <button
              onClick={() => onTest(account)}
              disabled={testingAccountId === account.id}
              className="rounded-lg border border-emerald-500/60 px-3 py-1.5 text-xs font-semibold text-emerald-300 transition hover:border-emerald-400 hover:text-emerald-200 disabled:opacity-60"
            >
              {testingAccountId === account.id ? 'Teste…' : 'Verbindung testen'}
            </button>
            <button
              onClick={() => onDelete(account)}
              className="rounded-lg border border-rose-600 px-3 py-1.5 text-xs font-semibold text-rose-200 transition hover:border-rose-500 hover:text-rose-100"
            >
              Löschen
            </button>
          </div>
          {testResults[account.id] && (
            <div
              className={`mt-3 rounded-lg border px-3 py-2 text-xs ${
                testResults[account.id].success
                  ? 'border-emerald-600 text-emerald-200'
                  : 'border-rose-600 text-rose-200'
              }`}
            >
              <p className="font-semibold">{testResults[account.id].message}</p>
              {testResults[account.id].details && (
                <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap text-[11px] text-slate-200/90">
                  {JSON.stringify(testResults[account.id].details, null, 2)}
                </pre>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
