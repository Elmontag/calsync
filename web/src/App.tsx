import { useState } from 'react';
import AccountForm from './components/AccountForm';
import AccountList from './components/AccountList';
import ConnectionTester from './components/ConnectionTester';
import EventTable from './components/EventTable';
import SyncMappingConfigurator from './components/SyncMappingConfigurator';
import { useAccounts, useEvents, useSyncMappings } from './api/hooks';

function App() {
  const [activeView, setActiveView] = useState<'sync' | 'accounts'>('sync');
  const { accounts, addAccount } = useAccounts();
  const { events, scan, manualSync, syncAll, autoSync, toggleAutoSync } = useEvents();
  const { mappings, addMapping, removeMapping } = useSyncMappings();

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
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-10">
        {activeView === 'sync' ? (
          <div className="grid gap-8 lg:grid-cols-3">
            <section className="lg:col-span-2 space-y-8">
              <EventTable
                events={events}
                onManualSync={manualSync}
                onScan={scan}
                onSyncAll={syncAll}
                autoSyncEnabled={autoSync.enabled}
                onAutoSyncToggle={toggleAutoSync}
              />
              <SyncMappingConfigurator
                accounts={accounts}
                mappings={mappings}
                onCreate={addMapping}
                onDelete={removeMapping}
              />
            </section>
            <aside className="space-y-8">
              <ConnectionTester />
            </aside>
          </div>
        ) : (
          <div className="grid gap-8 lg:grid-cols-2">
            <section className="space-y-6">
              <div className="rounded-xl border border-slate-800 bg-slate-900 p-6 shadow-lg shadow-emerald-500/10">
                <h2 className="text-lg font-semibold text-slate-100">Neues Konto</h2>
                <p className="mt-1 text-sm text-slate-400">
                  Hinterlege hier IMAP oder CalDAV Verbindungen inkl. Syncrichtung.
                </p>
                <div className="mt-6">
                  <AccountForm onSubmit={addAccount} />
                </div>
              </div>
            </section>
            <aside className="space-y-6">
              <AccountList accounts={accounts} />
            </aside>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
