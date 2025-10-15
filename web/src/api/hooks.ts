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
  SyncJobStatus,
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
    active_job: null,
  });

  async function refresh() {
    setLoading(true);
    try {
      const { data } = await api.get<TrackedEvent[]>('/events');
      setEvents(data);
    } catch (error) {
      // Keep the previous list of events visible so users are not left with an empty view.
      console.error('Konnte Termine nicht aktualisieren.', error);
    } finally {
      setLoading(false);
    }
  }

  async function loadAutoSync() {
    const { data } = await api.get<AutoSyncStatus>('/events/auto-sync');
    setAutoSync((prev) => ({
      enabled: data.enabled,
      interval_minutes: data.interval_minutes ?? prev.interval_minutes ?? 5,
      auto_response: data.auto_response ?? prev.auto_response ?? 'none',
      active_job: data.active_job ?? null,
    }));
  }

  useEffect(() => {
    refresh();
    loadAutoSync();
  }, []);

  async function scan() {
    const { data } = await api.post<SyncJobStatus>('/events/scan');
    return data;
  }

  async function manualSync(payload: ManualSyncRequest) {
    const { data } = await api.post<SyncJobStatus>('/events/manual-sync', payload);
    return data;
  }

  async function syncAll() {
    const { data } = await api.post<SyncJobStatus>('/events/sync-all');
    return data;
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
    setAutoSync((prev) => ({
      enabled: data.enabled,
      interval_minutes: data.interval_minutes ?? prev.interval_minutes ?? 5,
      auto_response: data.auto_response ?? prev.auto_response ?? 'none',
      active_job: data.active_job ?? null,
    }));
    return data;
  }

  async function toggleAutoSync(enabled: boolean) {
    await configureAutoSync({ enabled });
  }

  async function setAutoResponse(autoResponse: AutoSyncStatus['auto_response']) {
    await configureAutoSync({ enabled: autoSync.enabled, auto_response: autoResponse });
  }

  async function setAutoSyncInterval(intervalMinutes: number) {
    await configureAutoSync({ enabled: autoSync.enabled, interval_minutes: intervalMinutes });
  }

  async function getJobStatus(jobId: string) {
    const { data } = await api.get<SyncJobStatus>(`/jobs/${jobId}`);
    return data;
  }

  async function respondToEvent(eventId: number, response: TrackedEvent['response_status']) {
    const { data } = await api.post<TrackedEvent>(`/events/${eventId}/response`, { response });
    setEvents((prev) => prev.map((event) => (event.id === eventId ? data : event)));
    return data;
  }

  async function disableTracking(eventId: number) {
    const { data } = await api.post<TrackedEvent>(`/events/${eventId}/disable-tracking`);
    setEvents((prev) => prev.filter((event) => event.id !== eventId));
    return data;
  }

  return {
    events,
    loading,
    refresh,
    scan,
    manualSync,
    syncAll,
    getJobStatus,
    autoSync,
    toggleAutoSync,
    setAutoResponse,
    setAutoSyncInterval,
    respondToEvent,
    loadAutoSync,
    disableTracking,
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
