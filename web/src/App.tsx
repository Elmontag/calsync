import { useState } from 'react';
import AccountForm from './components/AccountForm';
import AccountList from './components/AccountList';
import EventTable from './components/EventTable';
import SyncMappingConfigurator from './components/SyncMappingConfigurator';
import { useAccounts, useEvents, useSyncMappings } from './api/hooks';
import type { Account, AccountCreateInput } from './types/api';

type ActiveView = 'sync' | 'accounts' | 'settings';

function App() {
  const [activeView, setActiveView] = useState<ActiveView>('sync');
  const { accounts, addAccount, updateAccount, removeAccount } = useAccounts();
  const {
    events,
    loading: eventsLoading,
    scan,
    manualSync,
    syncAll,
    refresh,
    getJobStatus,
    autoSync,
    toggleAutoSync,
    setAutoResponse,
    setAutoSyncInterval,
    respondToEvent,
  } = useEvents();
  const { mappings, addMapping, removeMapping } = useSyncMappings();
  const [editingAccount, setEditingAccount] = useState<Account | null>(null);
  const [savingAccount, setSavingAccount] = useState(false);

  async function handleAccountSubmit(values: AccountCreateInput) {
    setSavingAccount(true);
    try {
      if (editingAccount) {
        await updateAccount(editingAccount.id, values);
        setEditingAccount(null);
      } else {
        await addAccount(values);
      }
    } finally {
      setSavingAccount(false);
    }
  }

  async function handleDeleteAccount(account: Account) {
    const confirmed = window.confirm(`Konto "${account.label}" wirklich löschen?`);
    if (!confirmed) {
      return;
    }
    await removeAccount(account.id);
    if (editingAccount?.id === account.id) {
      setEditingAccount(null);
    }
  }

  function handleCancelEdit() {
    setEditingAccount(null);
  }

  return (
    <div className="min-h-screen bg-slate-950 pb-16">
      <header className="border-b border-slate-900 bg-slate-950/80">
        <div className="mx-auto flex max-w-6xl flex-col gap-2 px-6 py-6 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-2xl font-bold text-emerald-400">CalSync</h1>
            <p className="text-sm text-slate-400">
              Synchronisation von Mail-Terminen in CalDAV Kalender
            </p>
          </div>
          <div className="flex items-center gap-4 text-xs uppercase tracking-wide text-slate-500">
            <button
              onClick={() => setActiveView('sync')}
              className={`rounded-full px-3 py-1 text-xs font-semibold transition ${
                activeView === 'sync'
                  ? 'bg-emerald-500 text-emerald-950'
                  : 'bg-slate-800 text-slate-200 hover:bg-slate-700'
              }`}
            >
              Synchronisation
            </button>
            <button
              onClick={() => setActiveView('accounts')}
              className={`rounded-full px-3 py-1 text-xs font-semibold transition ${
                activeView === 'accounts'
                  ? 'bg-emerald-500 text-emerald-950'
                  : 'bg-slate-800 text-slate-200 hover:bg-slate-700'
              }`}
            >
              Konten ({accounts.length})
            </button>
            <button
              onClick={() => setActiveView('settings')}
              className={`rounded-full px-3 py-1 text-xs font-semibold transition ${
                activeView === 'settings'
                  ? 'bg-emerald-500 text-emerald-950'
                  : 'bg-slate-800 text-slate-200 hover:bg-slate-700'
              }`}
            >
              Einstellungen
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-10">
        {activeView === 'sync' && (
          <div className="space-y-8">
            <EventTable
              events={events}
              onManualSync={manualSync}
              onScan={scan}
              onSyncAll={syncAll}
              fetchJobStatus={getJobStatus}
              autoSyncEnabled={autoSync.enabled}
              autoSyncIntervalMinutes={autoSync.interval_minutes ?? 5}
              autoSyncResponse={autoSync.auto_response}
              onAutoSyncToggle={toggleAutoSync}
              onAutoSyncResponseChange={setAutoResponse}
              onAutoSyncIntervalChange={setAutoSyncInterval}
              onRespondToEvent={respondToEvent}
              onRefresh={refresh}
              loading={eventsLoading}
            />
          </div>
        )}

        {activeView === 'accounts' && (
          <div className="grid gap-8 lg:grid-cols-2">
            <section className="space-y-6">
              <div className="rounded-xl border border-slate-800 bg-slate-900 p-6 shadow-lg shadow-emerald-500/10">
                <h2 className="text-lg font-semibold text-slate-100">
                  {editingAccount ? 'Konto bearbeiten' : 'Neues Konto'}
                </h2>
                <p className="mt-1 text-sm text-slate-400">
                  {editingAccount
                    ? 'Passe Zugangsdaten und Ordnerzuweisungen für das ausgewählte Konto an.'
                    : 'Hinterlege hier IMAP oder CalDAV Verbindungen und teste deine Zugangsdaten direkt.'}
                </p>
                <div className="mt-6">
                  <AccountForm
                    account={editingAccount}
                    onSubmit={handleAccountSubmit}
                    onCancel={handleCancelEdit}
                    loading={savingAccount}
                  />
                </div>
              </div>
            </section>
            <aside className="space-y-6">
              <AccountList
                accounts={accounts}
                onEdit={setEditingAccount}
                onDelete={handleDeleteAccount}
                activeAccountId={editingAccount?.id ?? null}
              />
            </aside>
          </div>
        )}

        {activeView === 'settings' && (
          <div className="grid gap-8 lg:grid-cols-2">
            <section className="space-y-6">
              <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
                <h2 className="text-lg font-semibold text-slate-100">Sync-Zuordnungen verwalten</h2>
                <p className="mt-1 text-sm text-slate-400">
                  Definiere hier, welcher IMAP-Ordner in welchen CalDAV-Kalender exportiert wird. Die
                  Einstellungen werden sowohl für manuelle Exporte als auch für AutoSync verwendet.
                </p>
                <div className="mt-6">
                  <SyncMappingConfigurator
                    accounts={accounts}
                    mappings={mappings}
                    onCreate={addMapping}
                    onDelete={removeMapping}
                  />
                </div>
              </div>
            </section>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
