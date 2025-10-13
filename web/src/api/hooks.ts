import { useEffect, useState } from 'react';
import api from './client';
import {
  Account,
  AccountCreateInput,
  AccountUpdateInput,
  AutoSyncStatus,
  CalendarInfo,
  ConnectionTestRequest,
  ConnectionTestResult,
  ManualSyncRequest,
  SyncMapping,
  SyncMappingCreateInput,
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

  async function updateAccount(accountId: number, payload: AccountUpdateInput) {
    await api.put<Account>(`/accounts/${accountId}`, payload);
    await refresh();
  }

  async function removeAccount(accountId: number) {
    await api.delete(`/accounts/${accountId}`);
    await refresh();
  }

  return { accounts, loading, error, refresh, addAccount, updateAccount, removeAccount };
}

export async function runConnectionTest(payload: ConnectionTestRequest) {
  const { data } = await api.post<ConnectionTestResult>('/accounts/test', payload);
  return data;
}

export function useEvents() {
  const [events, setEvents] = useState<TrackedEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [autoSync, setAutoSync] = useState<AutoSyncStatus>({ enabled: false });

  async function refresh() {
    setLoading(true);
    const { data } = await api.get<TrackedEvent[]>('/events');
    setEvents(data);
    setLoading(false);
  }

  async function loadAutoSync() {
    const { data } = await api.get<AutoSyncStatus>('/events/auto-sync');
    setAutoSync(data);
  }

  useEffect(() => {
    refresh();
    loadAutoSync();
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

  async function syncAll() {
    await api.post('/events/sync-all');
    await refresh();
  }

  async function toggleAutoSync(enabled: boolean) {
    const { data } = await api.post<AutoSyncStatus>('/events/auto-sync', {
      enabled,
    });
    setAutoSync(data);
  }

  return { events, loading, refresh, scan, manualSync, syncAll, autoSync, toggleAutoSync, loadAutoSync };
}

export function useSyncMappings() {
  const [mappings, setMappings] = useState<SyncMapping[]>([]);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLoading(true);
    const { data } = await api.get<SyncMapping[]>('/sync-mappings');
    setMappings(data);
    setLoading(false);
  }

  useEffect(() => {
    refresh();
  }, []);

  async function addMapping(payload: SyncMappingCreateInput) {
    await api.post<SyncMapping>('/sync-mappings', payload);
    await refresh();
  }

  async function removeMapping(id: number) {
    await api.delete(`/sync-mappings/${id}`);
    await refresh();
  }

  return { mappings, loading, refresh, addMapping, removeMapping };
}

export async function fetchCalendars(accountId: number) {
  const { data } = await api.get<{ calendars: CalendarInfo[] }>(`/accounts/${accountId}/calendars`);
  return data.calendars;
}
