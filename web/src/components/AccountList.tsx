import { Account } from '../types/api';

interface Props {
  accounts: Account[];
}

export default function AccountList({ accounts }: Props) {
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
        <div key={account.id} className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <div className="flex items-start justify-between">
            <div>
              <h3 className="text-base font-semibold text-slate-100">{account.label}</h3>
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
        </div>
      ))}
    </div>
  );
}
