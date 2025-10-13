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
  ManualSyncResponse,
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
  const [autoSync, setAutoSync] = useState<AutoSyncStatus>({
    enabled: false,
    interval_minutes: 5,
    auto_response: 'none',
  });

  async function refresh() {
    setLoading(true);
    const { data } = await api.get<TrackedEvent[]>('/events');
    setEvents(data);
    setLoading(false);
  }

  async function loadAutoSync() {
    const { data } = await api.get<AutoSyncStatus>('/events/auto-sync');
    setAutoSync({
      enabled: data.enabled,
      interval_minutes: data.interval_minutes ?? autoSync.interval_minutes ?? 5,
      auto_response: data.auto_response ?? 'none',
    });
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
    const { data } = await api.post<ManualSyncResponse>('/events/manual-sync', payload);
    await refresh();
    return data;
  }

  async function syncAll() {
    await api.post('/events/sync-all');
    await refresh();
  }

  async function configureAutoSync(config: {
    enabled: boolean;
    auto_response?: AutoSyncStatus['auto_response'];
    interval_minutes?: number;
  }) {
    const { data } = await api.post<AutoSyncStatus>('/events/auto-sync', {
      enabled: config.enabled,
      interval_minutes: config.interval_minutes ?? autoSync.interval_minutes ?? 5,
      auto_response: config.auto_response ?? autoSync.auto_response ?? 'none',
    });
    setAutoSync(data);
    return data;
  }

  async function toggleAutoSync(enabled: boolean) {
    await configureAutoSync({ enabled });
  }

  async function setAutoResponse(autoResponse: AutoSyncStatus['auto_response']) {
    await configureAutoSync({ enabled: autoSync.enabled, auto_response: autoResponse });
  }

  async function respondToEvent(eventId: number, response: TrackedEvent['response_status']) {
    const { data } = await api.post<TrackedEvent>(`/events/${eventId}/response`, { response });
    setEvents((prev) => prev.map((event) => (event.id === eventId ? data : event)));
    return data;
  }

  return {
    events,
    loading,
    refresh,
    scan,
    manualSync,
    syncAll,
    autoSync,
    toggleAutoSync,
    setAutoResponse,
    respondToEvent,
    loadAutoSync,
  };
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
