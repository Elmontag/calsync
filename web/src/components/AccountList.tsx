import { Account } from '../types/api';

interface Props {
  accounts: Account[];
  onEdit: (account: Account) => void;
  onDelete: (account: Account) => void;
  activeAccountId?: number | null;
}

export default function AccountList({
  accounts,
  onEdit,
  onDelete,
  activeAccountId,
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
                {account.type === 'imap' ? 'IMAP' : 'CalDAV'}
              </p>
            </div>
            {account.type === 'imap' && (
              <span className="rounded-full bg-slate-800 px-3 py-1 text-xs text-slate-300">
                {account.imap_folders.length} Ordner
              </span>
            )}
          </div>
          {account.type === 'imap' && (
            <details className="mt-3 rounded-lg border border-slate-800 bg-slate-950/60">
              <summary className="cursor-pointer select-none px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
                Ordnerübersicht ({account.imap_folders.length})
              </summary>
              <ul className="space-y-1 border-t border-slate-800 px-3 py-3 text-sm text-slate-300">
                {account.imap_folders.length > 0 ? (
                  account.imap_folders.map((folder) => (
                    <li key={folder.name}>
                      {folder.name}
                      {folder.include_subfolders ? ' (inkl. Unterordner)' : ''}
                    </li>
                  ))
                ) : (
                  <li className="text-xs text-slate-500">Keine Ordner ausgewählt.</li>
                )}
              </ul>
            </details>
          )}
          <div className="mt-4 flex flex-wrap gap-2">
            <button
              onClick={() => onEdit(account)}
              className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs font-semibold text-slate-200 transition hover:border-slate-600 hover:text-slate-100"
            >
              Bearbeiten
            </button>
            <button
              onClick={() => onDelete(account)}
              className="rounded-lg border border-rose-600 px-3 py-1.5 text-xs font-semibold text-rose-200 transition hover:border-rose-500 hover:text-rose-100"
            >
              Löschen
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
