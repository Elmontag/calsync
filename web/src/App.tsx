import { useMemo, useState } from 'react';
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
    loadAutoSync,
    disableTracking,
    deleteMail,
    resolveConflict,
    ignoreEvent,
  } = useEvents();
  const { mappings, addMapping, removeMapping } = useSyncMappings();
  const [editingAccountId, setEditingAccountId] = useState<number | null>(null);
  const activeAccount = useMemo(
    () => accounts.find((account) => account.id === editingAccountId) ?? null,
    [accounts, editingAccountId],
  );
  const [savingAccount, setSavingAccount] = useState(false);
  const [accountFeedback, setAccountFeedback] = useState<
    { type: 'success' | 'error'; message: string }
  | null>(null);

  async function handleAccountSubmit(values: AccountCreateInput) {
    setSavingAccount(true);
    setAccountFeedback(null);
    try {
      if (editingAccountId !== null) {
        const updated = await updateAccount(editingAccountId, values);
        setAccountFeedback({
          type: 'success',
          message: 'Kontoeinstellungen wurden gespeichert.',
        });
        if (updated) {
          setEditingAccountId(updated.id);
        }
      } else {
        await addAccount(values);
        setAccountFeedback({
          type: 'success',
          message: 'Neues Konto wurde erfolgreich gespeichert.',
        });
      }
    } catch (error) {
      console.error('Konto konnte nicht gespeichert werden.', error);
      setAccountFeedback({
        type: 'error',
        message: 'Konto konnte nicht gespeichert werden. Bitte versuche es erneut.',
      });
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
    if (editingAccountId === account.id) {
      setEditingAccountId(null);
    }
    setAccountFeedback(null);
  }

  function handleCancelEdit() {
    setEditingAccountId(null);
    setAccountFeedback(null);
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
              onDisableTracking={disableTracking}
              onDeleteMail={deleteMail}
              onIgnoreEvent={ignoreEvent}
              onResolveConflict={resolveConflict}
              onRefresh={refresh}
              autoSyncJob={autoSync.active_job ?? null}
              onLoadAutoSync={loadAutoSync}
              loading={eventsLoading}
            />
          </div>
        )}

        {activeView === 'accounts' && (
          <div className="grid gap-8 lg:grid-cols-2">
            <section className="space-y-6">
              <div className="rounded-xl border border-slate-800 bg-slate-900 p-6 shadow-lg shadow-emerald-500/10">
                <h2 className="text-lg font-semibold text-slate-100">
                  {activeAccount ? 'Konto bearbeiten' : 'Neues Konto'}
                </h2>
                <p className="mt-1 text-sm text-slate-400">
                  {activeAccount
                    ? 'Passe Zugangsdaten und Ordnerzuweisungen für das ausgewählte Konto an.'
                    : 'Hinterlege hier IMAP oder CalDAV Verbindungen und teste deine Zugangsdaten direkt.'}
                </p>
                {accountFeedback && (
                  <div
                    className={`mt-4 rounded-lg border px-4 py-3 text-sm ${
                      accountFeedback.type === 'success'
                        ? 'border-emerald-500/60 bg-emerald-500/10 text-emerald-200'
                        : 'border-rose-500/60 bg-rose-500/10 text-rose-200'
                    }`}
                  >
                    {accountFeedback.message}
                  </div>
                )}
                <div className="mt-6">
                  <AccountForm
                    key={activeAccount ? activeAccount.id : 'new'}
                    account={activeAccount}
                    onSubmit={handleAccountSubmit}
                    onCancel={handleCancelEdit}
                    loading={savingAccount}
                  />
                </div>
              </div>
            </section>
            <aside className="space-y-6">
              <div className="rounded-xl border border-dashed border-emerald-500/40 bg-slate-900/60 p-4">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <h3 className="text-sm font-semibold text-slate-100">Neues Konto</h3>
                    <p className="text-xs text-slate-400">
                      Starte ein leeres Formular ohne vorhandene Daten.
                    </p>
                  </div>
                  <button
                    onClick={() => {
                      setEditingAccountId(null);
                      setAccountFeedback(null);
                    }}
                    className="rounded-lg bg-emerald-500/20 px-3 py-1 text-xs font-semibold text-emerald-200 transition hover:bg-emerald-500/30 hover:text-emerald-100"
                  >
                    Neues Konto
                  </button>
                </div>
              </div>
              <AccountList
                accounts={accounts}
                onEdit={(account) => {
                  setEditingAccountId(account.id);
                  setAccountFeedback(null);
                }}
                onDelete={handleDeleteAccount}
                activeAccountId={editingAccountId}
              />
            </aside>
          </div>
        )}

        {activeView === 'settings' && (
          <section>
            <SyncMappingConfigurator
              accounts={accounts}
              mappings={mappings}
              onCreate={addMapping}
              onDelete={removeMapping}
            />
          </section>
        )}
      </main>
    </div>
  );
}

export default App;
