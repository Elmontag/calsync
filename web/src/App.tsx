import AccountForm from './components/AccountForm';
import ConnectionTester from './components/ConnectionTester';
import EventTable from './components/EventTable';
import { useAccounts, useEvents } from './api/hooks';

function App() {
  const { accounts, addAccount } = useAccounts();
  const { events, scan, manualSync } = useEvents();

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
          <div className="text-xs uppercase tracking-wide text-slate-500">
            {accounts.length} konfigurierte Konten
          </div>
        </div>
      </header>

      <main className="mx-auto grid max-w-6xl gap-8 px-6 py-10 lg:grid-cols-3">
        <section className="lg:col-span-2 space-y-8">
          <EventTable events={events} onManualSync={manualSync} onScan={scan} />
        </section>
        <aside className="space-y-8">
          <div className="rounded-xl border border-slate-800 bg-slate-900 p-6 shadow-lg shadow-emerald-500/10">
            <h2 className="text-lg font-semibold text-slate-100">Neues Konto</h2>
            <p className="mt-1 text-sm text-slate-400">
              Hinterlege hier IMAP oder CalDAV Verbindungen inkl. Syncrichtung.
            </p>
            <div className="mt-6">
              <AccountForm onSubmit={addAccount} />
            </div>
          </div>
          <ConnectionTester />
        </aside>
      </main>
    </div>
  );
}

export default App;
