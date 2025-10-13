import { useEffect, useState } from 'react';
import api from './client';
import {
  Account,
  AccountCreateInput,
  ConnectionTestRequest,
  ConnectionTestResult,
  ManualSyncRequest,
  TrackedEvent,
} from '../types/api';

export function useAccounts() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      setLoading(true);
      const { data } = await api.get<Account[]>('/accounts');
      setAccounts(data);
      setError(null);
    } catch (err) {
      setError('Konnte Konten nicht laden.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function addAccount(payload: AccountCreateInput) {
    await api.post<Account>('/accounts', payload);
    await refresh();
  }

  return { accounts, loading, error, refresh, addAccount };
}

export async function runConnectionTest(payload: ConnectionTestRequest) {
  const { data } = await api.post<ConnectionTestResult>('/accounts/test', payload);
  return data;
}

export function useEvents() {
  const [events, setEvents] = useState<TrackedEvent[]>([]);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLoading(true);
    const { data } = await api.get<TrackedEvent[]>('/events');
    setEvents(data);
    setLoading(false);
  }

  useEffect(() => {
    refresh();
  }, []);

  async function scan() {
    await api.post('/events/scan');
    await refresh();
  }

  async function manualSync(payload: ManualSyncRequest) {
    const { data } = await api.post<{ uploaded: string[] }>('/events/manual-sync', payload);
    await refresh();
    return data;
  }

  return { events, loading, refresh, scan, manualSync };
}
