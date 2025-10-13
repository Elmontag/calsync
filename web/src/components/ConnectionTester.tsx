import { useState } from 'react';
import { ConnectionTestRequest, ConnectionTestResult } from '../types/api';
import { runConnectionTest } from '../api/hooks';

export default function ConnectionTester() {
  const [type, setType] = useState<'imap' | 'caldav'>('imap');
  const [settings, setSettings] = useState<Record<string, string>>({});
  const [result, setResult] = useState<ConnectionTestResult | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleTest() {
    setLoading(true);
    const payload: ConnectionTestRequest = { type, settings };
    try {
      const res = await runConnectionTest(payload);
      setResult(res);
    } catch (error) {
      setResult({ success: false, message: 'Verbindungstest fehlgeschlagen.' });
    } finally {
      setLoading(false);
    }
  }

  function renderFields() {
    if (type === 'imap') {
      return (
        <div className="grid grid-cols-2 gap-4">
          <input
            placeholder="Host"
            className="rounded border border-slate-700 bg-slate-900 p-2"
            onChange={(e) => setSettings((prev) => ({ ...prev, host: e.target.value }))}
          />
          <input
            placeholder="Port"
            className="rounded border border-slate-700 bg-slate-900 p-2"
            onChange={(e) => setSettings((prev) => ({ ...prev, port: e.target.value }))}
          />
          <input
            placeholder="Benutzername"
            className="rounded border border-slate-700 bg-slate-900 p-2"
            onChange={(e) => setSettings((prev) => ({ ...prev, username: e.target.value }))}
          />
          <input
            placeholder="Passwort"
            type="password"
            className="rounded border border-slate-700 bg-slate-900 p-2"
            onChange={(e) => setSettings((prev) => ({ ...prev, password: e.target.value }))}
          />
        </div>
      );
    }
    return (
      <div className="grid grid-cols-2 gap-4">
        <input
          placeholder="CalDAV URL"
          className="col-span-2 rounded border border-slate-700 bg-slate-900 p-2"
          onChange={(e) => setSettings((prev) => ({ ...prev, url: e.target.value }))}
        />
        <input
          placeholder="Benutzername"
          className="rounded border border-slate-700 bg-slate-900 p-2"
          onChange={(e) => setSettings((prev) => ({ ...prev, username: e.target.value }))}
        />
        <input
          placeholder="Passwort"
          type="password"
          className="rounded border border-slate-700 bg-slate-900 p-2"
          onChange={(e) => setSettings((prev) => ({ ...prev, password: e.target.value }))}
        />
      </div>
    );
  }

  return (
    <div className="space-y-4 rounded-xl border border-slate-800 bg-slate-900 p-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-100">Verbindungstest</h2>
        <select
          value={type}
          onChange={(event) => {
            setType(event.target.value as 'imap' | 'caldav');
            setSettings({});
            setResult(null);
          }}
          className="rounded border border-slate-700 bg-slate-900 px-3 py-2"
        >
          <option value="imap">IMAP</option>
          <option value="caldav">CalDAV</option>
        </select>
      </div>

      {renderFields()}

      <button
        onClick={handleTest}
        disabled={loading}
        className="rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-emerald-950 hover:bg-emerald-400 disabled:opacity-50"
      >
        {loading ? 'Teste...' : 'Test starten'}
      </button>

      {result && (
        <div
          className={`rounded border p-3 text-sm ${result.success ? 'border-emerald-600 text-emerald-300' : 'border-rose-600 text-rose-200'}`}
        >
          <p className="font-semibold">{result.message}</p>
          {result.details && (
            <pre className="mt-2 whitespace-pre-wrap text-xs text-slate-300">
              {JSON.stringify(result.details, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
