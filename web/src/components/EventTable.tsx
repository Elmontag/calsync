import { ChangeEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from 'react';
import {
  ManualSyncMissingDetail,
  ManualSyncRequest,
  ManualSyncResponse,
  SyncJobStatus,
  ConflictDifference,
  ConflictResolutionOption,
  TrackedEvent,
} from '../types/api';

interface Props {
  events: TrackedEvent[];
  onManualSync: (payload: ManualSyncRequest) => Promise<SyncJobStatus>;
  onScan: () => Promise<SyncJobStatus>;
  onSyncAll: () => Promise<SyncJobStatus>;
  fetchJobStatus: (jobId: string) => Promise<SyncJobStatus>;
  autoSyncEnabled: boolean;
  autoSyncIntervalMinutes: number;
  autoSyncResponse: TrackedEvent['response_status'];
  onAutoSyncToggle: (enabled: boolean) => Promise<void>;
  onAutoSyncResponseChange: (response: TrackedEvent['response_status']) => Promise<void>;
  onAutoSyncIntervalChange: (intervalMinutes: number) => Promise<void>;
  onRespondToEvent: (
    eventId: number,
    response: TrackedEvent['response_status'],
  ) => Promise<TrackedEvent>;
  onDisableTracking: (eventId: number) => Promise<TrackedEvent>;
  onDeleteMail: (eventId: number) => Promise<TrackedEvent>;
  onResolveConflict: (
    eventId: number,
    payload: { action: string; selections?: Record<string, 'email' | 'calendar'> },
  ) => Promise<TrackedEvent>;
  loading?: boolean;
  onRefresh: () => Promise<void>;
  autoSyncJob: SyncJobStatus | null;
  onLoadAutoSync: () => Promise<void>;
}

type MergeSelectionMap = Record<number, Record<string, 'email' | 'calendar'>>;

const statusLabelMap: Record<TrackedEvent['status'], string> = {
  new: 'Neu',
  updated: 'Aktualisiert',
  cancelled: 'Abgesagt',
  synced: 'Synchronisiert',
  failed: 'Fehlerhaft',
};

const statusStyleMap: Record<TrackedEvent['status'], string> = {
  new: 'bg-sky-500/10 text-sky-300',
  updated: 'bg-indigo-500/10 text-indigo-300',
  cancelled: 'bg-rose-500/10 text-rose-300',
  synced: 'bg-emerald-500/10 text-emerald-300',
  failed: 'bg-rose-600/20 text-rose-200',
};

const statusFilterOptions: Array<{ value: TrackedEvent['status']; label: string }> = [
  { value: 'new', label: statusLabelMap.new },
  { value: 'updated', label: statusLabelMap.updated },
  { value: 'cancelled', label: statusLabelMap.cancelled },
  { value: 'synced', label: statusLabelMap.synced },
  { value: 'failed', label: statusLabelMap.failed },
];

const responseLabelMap: Record<TrackedEvent['response_status'], string> = {
  none: 'Keine Antwort',
  accepted: 'Zusage',
  tentative: 'Vielleicht',
  declined: 'Absage',
};

const responseStyleMap: Record<TrackedEvent['response_status'], string> = {
  none: 'bg-slate-800 text-slate-200',
  accepted: 'bg-emerald-500/15 text-emerald-300',
  tentative: 'bg-amber-500/15 text-amber-300',
  declined: 'bg-rose-500/15 text-rose-300',
};

const attendeeStatusMap: Record<string, string> = {
  ACCEPTED: 'Zusage',
  TENTATIVE: 'Vorläufig',
  DECLINED: 'Absage',
};

const responseActions: Array<{
  value: TrackedEvent['response_status'];
  label: string;
  className: string;
}> = [
  { value: 'accepted', label: 'Zusage', className: 'bg-emerald-500 text-emerald-950 hover:bg-emerald-400' },
  { value: 'tentative', label: 'Vielleicht', className: 'bg-amber-500 text-amber-950 hover:bg-amber-400' },
  { value: 'declined', label: 'Absagen', className: 'bg-rose-500 text-rose-100 hover:bg-rose-400' },
];

type SortOption = 'email-desc' | 'email-asc' | 'event-asc' | 'event-desc' | 'none';

const sortOptionItems: Array<{ value: SortOption; label: string }> = [
  { value: 'email-desc', label: 'E-Mail-Datum (neueste zuerst)' },
  { value: 'email-asc', label: 'E-Mail-Datum (älteste zuerst)' },
  { value: 'event-asc', label: 'Termindatum (früheste zuerst)' },
  { value: 'event-desc', label: 'Termindatum (späteste zuerst)' },
  { value: 'none', label: 'Keine Sortierung' },
];

const PAGE_SIZE_OPTIONS = [10, 20, 50] as const;
type PageSize = (typeof PAGE_SIZE_OPTIONS)[number];
const DEFAULT_PAGE_SIZE: PageSize = 10;

function formatDateTime(value?: string) {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return date.toLocaleString();
}

function formatDateRange(event: TrackedEvent) {
  const start = formatDateTime(event.start);
  const end = formatDateTime(event.end);
  if (start && end) {
    return `${start} – ${end}`;
  }
  return start ?? end ?? 'Kein Zeitraum bekannt';
}

function formatConflictRange(conflict: TrackedEvent['conflicts'][number]) {
  const start = formatDateTime(conflict.start);
  const end = formatDateTime(conflict.end);
  if (start && end) {
    return `${start} – ${end}`;
  }
  return start ?? end ?? 'Keine Zeitangabe';
}

function formatDifferenceValue(difference: ConflictDifference, side: 'local' | 'remote') {
  const value = side === 'local' ? difference.local_value : difference.remote_value;
  if (!value) {
    return '–';
  }
  if (difference.field === 'start' || difference.field === 'end') {
    return formatDateTime(value) ?? value;
  }
  return value;
}

function formatSyncTimestamp(value?: string | null) {
  if (!value) {
    return 'Keine Angabe';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return 'Keine Angabe';
  }
  const datePart = date.toLocaleDateString('de-DE');
  const timePart = date.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
  return `${datePart} ${timePart}`;
}

const syncSourceLabels: Record<string, string> = {
  local: 'E-Mail-Import',
  remote: 'Kalenderdaten',
};

function parseIsoDate(value?: string | null): Date | null {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return date;
}

function getEmailDate(event: TrackedEvent): Date | null {
  return parseIsoDate(event.created_at) ?? parseIsoDate(event.history[0]?.timestamp ?? null);
}

function getEventDate(event: TrackedEvent): Date | null {
  return parseIsoDate(event.start) ?? parseIsoDate(event.end);
}

function sortHistoryEntries(entries: TrackedEvent['history']): TrackedEvent['history'] {
  const copy = [...entries];
  copy.sort((a, b) => {
    const timeA = a?.timestamp ? new Date(a.timestamp).getTime() : Number.NaN;
    const timeB = b?.timestamp ? new Date(b.timestamp).getTime() : Number.NaN;
    const normalizedA = Number.isNaN(timeA) ? 0 : timeA;
    const normalizedB = Number.isNaN(timeB) ? 0 : timeB;
    return normalizedB - normalizedA;
  });
  return copy;
}

type SortDirection = 'asc' | 'desc';

function compareByDate(
  a: TrackedEvent,
  b: TrackedEvent,
  getter: (event: TrackedEvent) => Date | null,
  direction: SortDirection,
): number {
  const dateA = getter(a);
  const dateB = getter(b);
  if (dateA && dateB) {
    const diff = dateA.getTime() - dateB.getTime();
    if (diff !== 0) {
      return direction === 'asc' ? diff : -diff;
    }
  } else if (dateA) {
    return -1;
  } else if (dateB) {
    return 1;
  }
  // Fallback to a deterministic ordering to keep the UI stable when dates are equal.
  return direction === 'asc' ? a.id - b.id : b.id - a.id;
}

export default function EventTable({
  events,
  onManualSync,
  onScan,
  onSyncAll,
  fetchJobStatus,
  autoSyncEnabled,
  autoSyncIntervalMinutes,
  autoSyncResponse,
  onAutoSyncToggle,
  onAutoSyncResponseChange,
  onAutoSyncIntervalChange,
  onRespondToEvent,
  onDisableTracking,
  onDeleteMail,
  onResolveConflict,
  loading = false,
  onRefresh,
  autoSyncJob,
  onLoadAutoSync,
}: Props) {
  const [selected, setSelected] = useState<number[]>([]);
  const [openItems, setOpenItems] = useState<number[]>([]);
  const [syncResult, setSyncResult] = useState<string[]>([]);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [syncNotice, setSyncNotice] = useState<string | null>(null);
  const [missing, setMissing] = useState<ManualSyncMissingDetail[]>([]);
  const [scanJob, setScanJob] = useState<SyncJobStatus | null>(null);
  const [syncAllJob, setSyncAllJob] = useState<SyncJobStatus | null>(null);
  const [selectionJob, setSelectionJob] = useState<SyncJobStatus | null>(null);
  const [autoJob, setAutoJob] = useState<SyncJobStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [respondingId, setRespondingId] = useState<number | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [sortOption, setSortOption] = useState<SortOption>('email-desc');
  const [statusFilters, setStatusFilters] = useState<TrackedEvent['status'][]>([]);
  const [syncConflictFilter, setSyncConflictFilter] = useState<'all' | 'sync-only'>('all');
  const [intervalInput, setIntervalInput] = useState(String(autoSyncIntervalMinutes));
  const [pageSize, setPageSize] = useState<PageSize>(DEFAULT_PAGE_SIZE);
  const [page, setPage] = useState(1);
  const [resolvingConflictId, setResolvingConflictId] = useState<number | null>(null);
  const [mailActionId, setMailActionId] = useState<number | null>(null);
  const [expandedDifferences, setExpandedDifferences] = useState<Record<number, boolean>>({});
  const [activeMergeId, setActiveMergeId] = useState<number | null>(null);
  const [mergeSelections, setMergeSelections] = useState<MergeSelectionMap>({});
  const pollersRef = useRef<Record<string, number>>({});

  useEffect(() => {
    return () => {
      Object.values(pollersRef.current).forEach((id) => {
        window.clearInterval(id);
      });
    };
  }, []);

  // Remove selections for events that disappeared after refresh.
  useEffect(() => {
    const eventMap = new Map(events.map((event) => [event.id, event]));
    setSelected((prev) =>
      prev.filter((id) => {
        const match = eventMap.get(id);
        if (!match) {
          return false;
        }
        return !(match.sync_state?.has_conflict ?? false);
      }),
    );
    setOpenItems((prev) => prev.filter((id) => eventMap.has(id)));
  }, [events]);

  useEffect(() => {
    setStatusFilters((prev) =>
      prev.filter((status) => events.some((event) => event.status === status)),
    );
  }, [events]);

  useEffect(() => {
    setIntervalInput(String(autoSyncIntervalMinutes));
  }, [autoSyncIntervalMinutes]);

  useEffect(() => {
    setPage(1);
  }, [searchTerm, statusFilters, sortOption, pageSize, syncConflictFilter]);

  // Compose the visible event list by applying search, status filters and sorting preferences.
  const filteredEvents = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    const hasTerm = term.length > 0;
    const statusSet = new Set(statusFilters);

    const filtered = events.filter((event) => {
      if (statusSet.size > 0 && !statusSet.has(event.status)) {
        return false;
      }
      if (syncConflictFilter === 'sync-only' && !(event.sync_state?.has_conflict ?? false)) {
        return false;
      }
      if (!hasTerm) {
        return true;
      }
      const haystack = [
        event.summary ?? '',
        event.uid,
        event.organizer ?? '',
        event.source_folder ?? '',
        event.status,
        event.response_status,
        event.source_account_id ? String(event.source_account_id) : '',
        event.conflicts?.map((conflict) => conflict.summary ?? conflict.uid).join(' ') ?? '',
      ]
        .join(' ')
        .toLowerCase();
      return haystack.includes(term);
    });

    const sorted = [...filtered];
    switch (sortOption) {
      case 'email-asc':
        sorted.sort((a, b) => compareByDate(a, b, getEmailDate, 'asc'));
        break;
      case 'event-asc':
        sorted.sort((a, b) => compareByDate(a, b, getEventDate, 'asc'));
        break;
      case 'event-desc':
        sorted.sort((a, b) => compareByDate(a, b, getEventDate, 'desc'));
        break;
      case 'none':
        break;
      case 'email-desc':
      default:
        sorted.sort((a, b) => compareByDate(a, b, getEmailDate, 'desc'));
        break;
    }

    return sorted;
  }, [events, searchTerm, statusFilters, sortOption, syncConflictFilter]);

  const totalPages = useMemo(() => {
    return Math.max(1, Math.ceil(filteredEvents.length / pageSize));
  }, [filteredEvents, pageSize]);

  const paginatedEvents = useMemo(() => {
    const start = (page - 1) * pageSize;
    return filteredEvents.slice(start, start + pageSize);
  }, [filteredEvents, page, pageSize]);

  const totalEvents = filteredEvents.length;
  const pageStart = totalEvents === 0 ? 0 : (page - 1) * pageSize + 1;
  const pageEnd = totalEvents === 0 ? 0 : Math.min(page * pageSize, totalEvents);

  useEffect(() => {
    setPage((prev) => Math.min(prev, totalPages));
  }, [totalPages]);

  // Aggregate key performance indicators for the overview widgets.
  const metrics = useMemo(() => {
    const outstanding = events.filter(
      (event) => event.status === 'new' || event.status === 'updated',
    ).length;
    const processed = events.filter((event) => event.status === 'synced').length;
    const cancelled = events.filter((event) => event.status === 'cancelled').length;
    const awaitingDecision = events.filter(
      (event) =>
        event.response_status === 'none' &&
        event.status !== 'cancelled' &&
        event.status !== 'failed',
    ).length;
    const conflicts = events.filter((event) => (event.conflicts?.length ?? 0) > 0).length;
    const syncConflicts = events.filter((event) => event.sync_state?.has_conflict).length;
    const todayStart = new Date();
    todayStart.setHours(0, 0, 0, 0);
    const todayEnd = new Date();
    todayEnd.setHours(23, 59, 59, 999);
    const today = events.filter((event) => {
      if (!event.start) {
        return false;
      }
      const startDate = new Date(event.start);
      return startDate >= todayStart && startDate <= todayEnd;
    }).length;
    return { outstanding, processed, cancelled, awaitingDecision, today, conflicts, syncConflicts };
  }, [events]);

  const showOnlySyncConflicts = syncConflictFilter === 'sync-only';

  function toggleSelection(id: number) {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id],
    );
  }

  function toggleOpen(id: number) {
    setOpenItems((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id],
    );
  }

  function handleSortChange(event: ChangeEvent<HTMLSelectElement>) {
    setSortOption(event.target.value as SortOption);
  }

  function toggleStatusFilter(status: TrackedEvent['status']) {
    setStatusFilters((prev) =>
      prev.includes(status) ? prev.filter((item) => item !== status) : [...prev, status],
    );
  }

  function toggleSyncConflictFilter() {
    setSyncConflictFilter((prev) => (prev === 'sync-only' ? 'all' : 'sync-only'));
  }

  function resetStatusFilters() {
    setStatusFilters([]);
  }

  function handlePageSizeChange(event: ChangeEvent<HTMLSelectElement>) {
    setPageSize(Number(event.target.value) as PageSize);
  }

  function goToPreviousPage() {
    setPage((prev) => Math.max(1, prev - 1));
  }

  function goToNextPage() {
    setPage((prev) => Math.min(totalPages, prev + 1));
  }

  function asNumber(value: unknown, fallback = 0): number {
    if (typeof value === 'number' && Number.isFinite(value)) {
      return value;
    }
    if (typeof value === 'string') {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) {
        return parsed;
      }
    }
    return fallback;
  }

  function clearPoller(key: 'scan' | 'syncAll' | 'selection' | 'autoSync') {
    const existing = pollersRef.current[key];
    if (existing) {
      window.clearInterval(existing);
      delete pollersRef.current[key];
    }
  }

  function trackJob(
    key: 'scan' | 'syncAll' | 'selection' | 'autoSync',
    initial: SyncJobStatus,
    setter: (status: SyncJobStatus) => void,
    onComplete?: (status: SyncJobStatus) => void,
  ) {
    setter(initial);
    if (initial.status === 'completed' || initial.status === 'failed') {
      onComplete?.(initial);
      return;
    }
    clearPoller(key);
    const poll = async () => {
      try {
        const next = await fetchJobStatus(initial.job_id);
        setter(next);
        if (next.status === 'completed' || next.status === 'failed') {
          clearPoller(key);
          onComplete?.(next);
        }
      } catch (error) {
        clearPoller(key);
        setBusy(false);
        setSyncError('Fortschritt konnte nicht geladen werden.');
      }
    };
    void poll();
    pollersRef.current[key] = window.setInterval(() => {
      void poll();
    }, 1500);
  }

  useEffect(() => {
    if (!autoSyncJob) {
      clearPoller('autoSync');
      setAutoJob(null);
      return;
    }
    trackJob('autoSync', autoSyncJob, setAutoJob, handleAutoSyncJobComplete);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoSyncJob?.job_id]);

  function parseManualSyncDetail(
    detail: SyncJobStatus['detail'] | null | undefined,
  ): ManualSyncResponse | null {
    if (!detail || typeof detail !== 'object') {
      return null;
    }
    const record = detail as Record<string, unknown>;
    const uploadedRaw = record.uploaded;
    const missingRaw = record.missing;
    const uploaded = Array.isArray(uploadedRaw)
      ? uploadedRaw.map((item) => String(item))
      : [];
    const missingList: ManualSyncMissingDetail[] = Array.isArray(missingRaw)
      ? missingRaw
          .filter((item): item is Record<string, unknown> => !!item && typeof item === 'object')
          .map((item) => {
            const accountCandidate =
              typeof item.account_id === 'number'
                ? item.account_id
                : typeof item.account_id === 'string' && item.account_id.trim() !== ''
                ? Number(item.account_id)
                : undefined;
            return {
              event_id: asNumber(item.event_id, 0),
              uid: typeof item.uid === 'string' ? item.uid : undefined,
              account_id:
                typeof accountCandidate === 'number' && Number.isFinite(accountCandidate)
                  ? accountCandidate
                  : undefined,
              folder: typeof item.folder === 'string' ? item.folder : undefined,
              reason:
                typeof item.reason === 'string' ? item.reason : 'Keine Zuordnung gefunden',
            };
          })
      : [];

    return {
      uploaded,
      missing: missingList,
    };
  }

  function handleScanJobComplete(status: SyncJobStatus) {
    setBusy(false);
    setScanJob(null);
    if (status.status === 'failed') {
      setSyncError(status.message ?? 'Postfach-Scan fehlgeschlagen.');
      return;
    }
    const detail = (status.detail ?? {}) as Record<string, unknown>;
    const messages = asNumber(detail.messages_processed ?? status.processed, status.processed);
    const eventsImported = asNumber(detail.events_imported ?? 0, 0);
    setSyncNotice(
      `Postfächer gescannt (${messages} Nachrichten geprüft, ${eventsImported} Termine verarbeitet).`,
    );
    setSyncError(null);
    void onRefresh();
  }

  function handleManualJobComplete(status: SyncJobStatus) {
    setBusy(false);
    setSelectionJob(null);
    if (status.status === 'failed') {
      setSyncResult([]);
      setMissing([]);
      setSyncNotice(null);
      setSyncError(status.message ?? 'Synchronisation fehlgeschlagen.');
      return;
    }
    const detail = parseManualSyncDetail(status.detail);
    const uploaded = detail?.uploaded ?? [];
    const missingDetails = detail?.missing ?? [];
    setSyncResult(uploaded);
    setMissing(missingDetails);
    if (missingDetails.length > 0) {
      setSyncError('Einige Termine konnten nicht synchronisiert werden.');
      setSelected(
        missingDetails
          .map((item) => item.event_id)
          .filter((id) => Number.isFinite(id) && id > 0),
      );
      setSyncNotice(null);
    } else if (uploaded.length === 0) {
      setSyncError('Keine Termine konnten synchronisiert werden.');
      setSyncNotice(null);
    } else {
      setSyncError(null);
      setSyncNotice('Ausgewählte Termine wurden synchronisiert.');
      setSelected([]);
    }
    void onRefresh();
  }

  function handleSyncAllJobComplete(status: SyncJobStatus) {
    setBusy(false);
    setSyncAllJob(null);
    if (status.status === 'failed') {
      setSyncError(status.message ?? 'Synchronisation fehlgeschlagen.');
      return;
    }
    const detail = (status.detail ?? {}) as Record<string, unknown>;
    const uploadedCount = asNumber(detail.uploaded ?? status.processed, status.processed);
    if (uploadedCount > 0) {
      setSyncNotice(`${uploadedCount} Termine wurden synchronisiert.`);
    } else {
      setSyncNotice('Alle Zuordnungen wurden synchronisiert, es gab keine Änderungen.');
    }
    setSyncError(null);
    void onRefresh();
  }

  function handleAutoSyncJobComplete(status: SyncJobStatus) {
    if (status.status === 'failed') {
      setSyncError(status.message ?? 'AutoSync fehlgeschlagen.');
      setSyncNotice(null);
    } else {
      const detail = (status.detail ?? {}) as Record<string, unknown>;
      const uploadedCount = asNumber(detail.uploaded ?? status.processed, status.processed);
      if (uploadedCount > 0) {
        setSyncNotice(`AutoSync hat ${uploadedCount} Termine aktualisiert.`);
      } else {
        setSyncNotice('AutoSync ausgeführt (keine Änderungen erforderlich).');
      }
      setSyncError(null);
    }
    void onRefresh();
    void onLoadAutoSync();
  }

  async function handleSyncSelection() {
    if (selected.length === 0) {
      return;
    }
    setBusy(true);
    setSyncError(null);
    setSyncNotice(null);
    setMissing([]);
    setSyncResult([]);
    try {
      const payload: ManualSyncRequest = { event_ids: selected };
      const job = await onManualSync(payload);
      trackJob('selection', job, setSelectionJob, handleManualJobComplete);
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      if (typeof detail === 'string') {
        setSyncError(detail);
      } else if (detail && typeof detail.message === 'string') {
        setSyncError(detail.message);
      } else {
        setSyncError('Synchronisation konnte nicht gestartet werden.');
      }
      setBusy(false);
    }
  }

  async function handleSyncAll() {
    setBusy(true);
    setSyncError(null);
    setSyncNotice(null);
    try {
      const job = await onSyncAll();
      trackJob('syncAll', job, setSyncAllJob, handleSyncAllJobComplete);
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      setSyncError(
        typeof detail === 'string'
          ? detail
          : 'Synchronisation aller Termine konnte nicht gestartet werden.',
      );
      setBusy(false);
    }
  }

  async function handleScan() {
    setBusy(true);
    setSyncError(null);
    setSyncNotice(null);
    try {
      const job = await onScan();
      trackJob('scan', job, setScanJob, handleScanJobComplete);
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      setSyncError(
        typeof detail === 'string'
          ? detail
          : 'Postfach-Scan konnte nicht gestartet werden.',
      );
      setBusy(false);
    }
  }

  function renderJobProgress(
    job: SyncJobStatus | null,
    label: string,
    accentClass: string,
  ) {
    if (!job) {
      return null;
    }
    const total = job.total ?? 0;
    const processed = job.processed ?? 0;
    const normalizedTotal = total > 0 ? total : 0;
    const normalizedProcessed =
      normalizedTotal > 0 ? Math.min(processed, normalizedTotal) : processed;
    const detail =
      job.detail && typeof job.detail === 'object'
        ? (job.detail as Record<string, unknown>)
        : null;
    const detailProcessed = detail ? asNumber(detail.processed, normalizedProcessed) : normalizedProcessed;
    const detailTotal = detail ? asNumber(detail.total, normalizedTotal) : normalizedTotal;
    const percent =
      detailTotal > 0
        ? Math.min(100, Math.round((detailProcessed / detailTotal) * 100))
        : job.status === 'completed'
        ? 100
        : 0;
    const statusLabel =
      job.status === 'failed'
        ? 'Fehlgeschlagen'
        : job.status === 'completed'
        ? 'Abgeschlossen'
        : 'Läuft…';
    const description =
      detail && typeof detail.description === 'string'
        ? (detail.description as string)
        : statusLabel;
    const phaseLabel =
      detail && typeof detail.phase === 'string' ? (detail.phase as string) : undefined;
    return (
      <div className="w-full rounded-xl border border-slate-800 bg-slate-950/80 p-4" key={label}>
        <div className="flex items-center justify-between text-xs text-slate-300">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-slate-100">{label}</span>
            {phaseLabel && (
              <span className="rounded-full bg-slate-800 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-500">
                {phaseLabel}
              </span>
            )}
          </div>
          <span>
            {statusLabel}
            {detailTotal > 0 ? ` · ${detailProcessed}/${detailTotal}` : ''}
          </span>
        </div>
        <p className="mt-2 text-xs text-slate-400">{description}</p>
        <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-slate-800">
          <div className={`h-full transition-all ${accentClass}`} style={{ width: `${percent}%` }} />
        </div>
      </div>
    );
  }

  async function handleAutoSyncToggle() {
    setBusy(true);
    try {
      await onAutoSyncToggle(!autoSyncEnabled);
    } finally {
      setBusy(false);
    }
  }

  async function handleAutoResponseToggle() {
    setBusy(true);
    setSyncError(null);
    setSyncResult([]);
    setMissing([]);
    try {
      const next = autoSyncResponse === 'accepted' ? 'none' : 'accepted';
      await onAutoSyncResponseChange(next);
      setSyncNotice(
        next === 'accepted'
          ? 'AutoSync bestätigt Termine jetzt automatisch.'
          : 'AutoSync sendet keine automatische Antwort mehr.',
      );
    } catch (error) {
      setSyncError('AutoSync-Einstellung konnte nicht gespeichert werden.');
    } finally {
      setBusy(false);
    }
  }

  async function applyAutoSyncIntervalChange() {
    const trimmed = intervalInput.trim();
    if (trimmed === '') {
      setIntervalInput(String(autoSyncIntervalMinutes));
      return;
    }

    const next = Number(trimmed);
    if (!Number.isFinite(next)) {
      setIntervalInput(String(autoSyncIntervalMinutes));
      setSyncError('Bitte eine gültige Zahl für das AutoSync-Intervall eingeben.');
      setSyncResult([]);
      setMissing([]);
      setSyncNotice(null);
      return;
    }

    const normalized = Math.round(next);
    if (normalized < 1 || normalized > 720) {
      setIntervalInput(String(autoSyncIntervalMinutes));
      setSyncError('Das AutoSync-Intervall muss zwischen 1 und 720 Minuten liegen.');
      setSyncResult([]);
      setMissing([]);
      setSyncNotice(null);
      return;
    }

    if (normalized === autoSyncIntervalMinutes) {
      setIntervalInput(String(normalized));
      return;
    }

    setBusy(true);
    setSyncError(null);
    setSyncResult([]);
    setMissing([]);
    try {
      await onAutoSyncIntervalChange(normalized);
      const label = normalized === 1 ? 'Minute' : 'Minuten';
      setIntervalInput(String(normalized));
      setSyncNotice(`AutoSync läuft jetzt alle ${normalized} ${label}.`);
    } catch (error) {
      setIntervalInput(String(autoSyncIntervalMinutes));
      setSyncError('AutoSync-Intervall konnte nicht gespeichert werden.');
    } finally {
      setBusy(false);
    }
  }

  function handleAutoSyncIntervalInput(event: ChangeEvent<HTMLInputElement>) {
    setIntervalInput(event.target.value);
  }

  function handleAutoSyncIntervalBlur() {
    void applyAutoSyncIntervalChange();
  }

  function handleAutoSyncIntervalKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Enter') {
      event.preventDefault();
      void applyAutoSyncIntervalChange();
    }
    if (event.key === 'Escape') {
      setIntervalInput(String(autoSyncIntervalMinutes));
      setSyncError(null);
    }
  }

  async function handleResponse(event: TrackedEvent, response: TrackedEvent['response_status']) {
    if (respondingId !== null) {
      return;
    }
    if (event.response_status === response) {
      return;
    }
    setRespondingId(event.id);
    setSyncError(null);
    setSyncResult([]);
    setMissing([]);
    try {
      const updated = await onRespondToEvent(event.id, response);
      const title = updated.summary ?? updated.uid;
      if (response === 'none') {
        setSyncNotice(`Antwort für "${title}" wurde zurückgesetzt.`);
      } else {
        const label = responseLabelMap[response];
        setSyncNotice(`Antwort für "${title}" wurde auf ${label} gesetzt.`);
      }
    } catch (error) {
      setSyncError('Teilnahmestatus konnte nicht gespeichert werden.');
    } finally {
      setRespondingId(null);
    }
  }

  async function handleDisableTracking(event: TrackedEvent) {
    if (resolvingConflictId !== null) {
      return;
    }
    if (mailActionId !== null) {
      return;
    }
    setResolvingConflictId(event.id);
    setSyncError(null);
    setSyncResult([]);
    setMissing([]);
    try {
      await onDisableTracking(event.id);
      const title = event.summary ?? event.uid;
      setSyncNotice(`"${title}" wird bei zukünftigen Scans ignoriert.`);
      resetMerge(event.id);
      await onRefresh();
    } catch (error) {
      console.error('Konnte Tracking nicht deaktivieren.', error);
      setSyncError('Tracking konnte nicht deaktiviert werden.');
    } finally {
      setResolvingConflictId(null);
    }
  }

  async function handleDeleteMail(event: TrackedEvent) {
    if (mailActionId !== null) {
      return;
    }
    if (resolvingConflictId !== null) {
      return;
    }
    setMailActionId(event.id);
    setSyncError(null);
    setSyncResult([]);
    setMissing([]);
    try {
      const updated = await onDeleteMail(event.id);
      const title = updated.summary ?? updated.uid;
      setSyncNotice(`E-Mail für "${title}" wurde im Postfach gelöscht.`);
      await onRefresh();
    } catch (error) {
      console.error('Konnte E-Mail nicht löschen.', error);
      setSyncError('Die E-Mail konnte nicht gelöscht werden.');
    } finally {
      setMailActionId(null);
    }
  }

  function toggleDifferences(eventId: number) {
    setExpandedDifferences((prev) => ({
      ...prev,
      [eventId]: !prev[eventId],
    }));
  }

  function initializeMerge(event: TrackedEvent, differences: ConflictDifference[]) {
    const defaults: Record<string, 'email' | 'calendar'> = {};
    differences.forEach((difference) => {
      defaults[difference.field] = difference.field === 'response_status' ? 'email' : 'calendar';
    });
    setMergeSelections((prev) => ({
      ...prev,
      [event.id]: defaults,
    }));
    setActiveMergeId(event.id);
    setExpandedDifferences((prev) => ({
      ...prev,
      [event.id]: true,
    }));
  }

  function updateMergeSelection(eventId: number, field: string, source: 'email' | 'calendar') {
    setMergeSelections((prev) => ({
      ...prev,
      [eventId]: {
        ...(prev[eventId] ?? {}),
        [field]: source,
      },
    }));
  }

  function resetMerge(eventId: number) {
    setMergeSelections((prev) => {
      const { [eventId]: _removed, ...rest } = prev;
      return rest;
    });
    setActiveMergeId((current) => (current === eventId ? null : current));
  }

  async function resolveConflict(
    event: TrackedEvent,
    action: 'overwrite-calendar' | 'skip-email-import' | 'merge-fields',
    selections: Record<string, 'email' | 'calendar'> = {},
  ) {
    if (resolvingConflictId !== null) {
      return;
    }
    setResolvingConflictId(event.id);
    setSyncError(null);
    setSyncResult([]);
    setMissing([]);
    try {
      const updated = await onResolveConflict(event.id, { action, selections });
      const title = updated.summary ?? updated.uid;
      if (action === 'overwrite-calendar') {
        setSyncNotice(`Kalenderdaten für "${title}" wurden mit dem E-Mail-Import überschrieben.`);
      } else if (action === 'skip-email-import') {
        setSyncNotice(
          `Kalenderdaten für "${title}" wurden beibehalten. Hinweis: Wenn erneut abweichende E-Mail-Daten eintreffen, kann wieder ein Konflikt entstehen.`,
        );
      } else {
        setSyncNotice(`Konflikt für "${title}" wurde erfolgreich zusammengeführt.`);
      }
      resetMerge(event.id);
    } catch (error) {
      console.error('Konflikt konnte nicht gelöst werden.', error);
      setSyncError('Konflikt konnte nicht gelöst werden.');
    } finally {
      setResolvingConflictId(null);
    }
  }

  async function applyMerge(event: TrackedEvent) {
    const selections = mergeSelections[event.id] ?? {};
    await resolveConflict(event, 'merge-fields', selections);
  }

  function handleSuggestionClick(
    event: TrackedEvent,
    suggestion: ConflictResolutionOption,
  ) {
    if (suggestion.action === 'disable-tracking') {
      void handleDisableTracking(event);
      return;
    }
    const differences = event.sync_state?.conflict_details?.differences ?? [];
    if (suggestion.action === 'merge-fields') {
      if (differences.length === 0) {
        void resolveConflict(event, 'merge-fields');
        return;
      }
      initializeMerge(event, differences);
      return;
    }
    void resolveConflict(event, suggestion.action as 'overwrite-calendar' | 'skip-email-import');
  }

  const showInitialLoading = loading && events.length === 0;
  const showEmptyState = !loading && filteredEvents.length === 0;

  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
          <p className="text-xs uppercase tracking-wide text-slate-500">Ausstehend</p>
          <p className="mt-1 text-2xl font-semibold text-slate-100">{metrics.outstanding}</p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
          <p className="text-xs uppercase tracking-wide text-slate-500">Verarbeitet</p>
          <p className="mt-1 text-2xl font-semibold text-emerald-400">{metrics.processed}</p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
          <p className="text-xs uppercase tracking-wide text-slate-500">Abgesagt</p>
          <p className="mt-1 text-2xl font-semibold text-rose-300">{metrics.cancelled}</p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
          <p className="text-xs uppercase tracking-wide text-slate-500">Antwort offen</p>
          <p className="mt-1 text-2xl font-semibold text-amber-300">{metrics.awaitingDecision}</p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
          <p className="text-xs uppercase tracking-wide text-slate-500">Heute</p>
          <p className="mt-1 text-2xl font-semibold text-sky-300">{metrics.today}</p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
          <p className="text-xs uppercase tracking-wide text-slate-500">Kalender-Konflikte</p>
          <p className="mt-1 text-2xl font-semibold text-amber-300">{metrics.conflicts}</p>
          <p className="mt-2 text-xs text-slate-400">
            Sync-Konflikte:{' '}
            <span className="font-semibold text-rose-300">{metrics.syncConflicts}</span>
          </p>
        </div>
      </div>

        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 shadow-lg shadow-emerald-500/5">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex flex-wrap items-center gap-2">
              <button
                onClick={handleScan}
              disabled={busy}
              className="rounded-lg bg-slate-800 px-4 py-2 text-sm font-semibold text-slate-100 transition hover:bg-slate-700 disabled:opacity-40"
            >
              Postfächer scannen
            </button>
            <button
              onClick={handleSyncAll}
              disabled={busy}
              className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-semibold text-sky-950 transition hover:bg-sky-500 disabled:opacity-40"
            >
              Alle synchronisieren
            </button>
            <button
              onClick={handleAutoSyncToggle}
              disabled={busy}
              className={`rounded-lg px-4 py-2 text-sm font-semibold transition disabled:opacity-40 ${
                autoSyncEnabled
                  ? 'bg-emerald-500 text-emerald-950 hover:bg-emerald-400'
                  : 'bg-slate-800 text-slate-100 hover:bg-slate-700'
              }`}
            >
              {autoSyncEnabled ? 'AutoSync deaktivieren' : 'AutoSync aktivieren'}
            </button>
            <button
              onClick={handleSyncSelection}
              disabled={selected.length === 0 || busy}
              className="rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-emerald-950 transition hover:bg-emerald-400 disabled:opacity-50"
            >
              Auswahl synchronisieren ({selected.length})
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-4">
            <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-300">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-slate-600 bg-slate-950"
                checked={autoSyncResponse === 'accepted'}
                onChange={handleAutoResponseToggle}
                disabled={busy}
              />
              <span>AutoSync sagt Termine automatisch zu</span>
            </label>
            <label className="flex items-center gap-2 text-xs text-slate-300">
              <span>AutoSync-Intervall (Minuten)</span>
              <input
                type="number"
                min={1}
                max={720}
                step={1}
                value={intervalInput}
                onChange={handleAutoSyncIntervalInput}
                onBlur={handleAutoSyncIntervalBlur}
                onKeyDown={handleAutoSyncIntervalKeyDown}
                disabled={busy}
                className="w-24 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-emerald-400 focus:outline-none disabled:opacity-50"
                aria-label="AutoSync-Intervall in Minuten"
              />
            </label>
            <div className="relative">
              <input
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
                className="w-64 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-emerald-400 focus:outline-none"
                placeholder="Termine suchen…"
                />
              </div>
            </div>
          </div>
          <div className="mt-3 flex flex-col gap-3 border-t border-slate-800 pt-3 md:flex-row md:items-center md:justify-between">
            <div className="flex flex-wrap items-center gap-3 text-xs text-slate-300">
              <label className="flex items-center gap-2">
                <span className="font-semibold uppercase tracking-wide text-slate-400">Sortierung</span>
                <select
                  value={sortOption}
                  onChange={handleSortChange}
                  className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-emerald-400 focus:outline-none"
                >
                  {sortOptionItems.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex items-center gap-2">
                <span className="font-semibold uppercase tracking-wide text-slate-400">Termine pro Seite</span>
                <select
                  value={pageSize}
                  onChange={handlePageSizeChange}
                  className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-emerald-400 focus:outline-none"
                >
                  {PAGE_SIZE_OPTIONS.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">Statusfilter</span>
              <button
                type="button"
                onClick={resetStatusFilters}
                className={`rounded-full border px-3 py-1 text-xs font-semibold transition ${
                  statusFilters.length === 0
                    ? 'border-emerald-400 bg-emerald-500/20 text-emerald-200'
                    : 'border-slate-700 text-slate-300 hover:border-emerald-400 hover:text-emerald-200'
                }`}
              >
                Alle Stati
              </button>
              {statusFilterOptions.map((option) => {
                const active = statusFilters.includes(option.value);
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => toggleStatusFilter(option.value)}
                    className={`rounded-full border px-3 py-1 text-xs font-semibold transition ${
                      active
                        ? 'border-emerald-400 bg-emerald-500/20 text-emerald-200'
                        : 'border-slate-700 text-slate-300 hover:border-emerald-400 hover:text-emerald-200'
                    }`}
                  >
                    {option.label}
                  </button>
                );
              })}
              <button
                type="button"
                onClick={toggleSyncConflictFilter}
                aria-pressed={showOnlySyncConflicts}
                className={`rounded-full border px-3 py-1 text-xs font-semibold transition ${
                  showOnlySyncConflicts
                    ? 'border-rose-400 bg-rose-500/20 text-rose-200'
                    : 'border-slate-700 text-slate-300 hover:border-rose-400 hover:text-rose-200'
                }`}
              >
                Nur Sync-Konflikte
              </button>
            </div>
          </div>
        </div>

        {(scanJob || syncAllJob || selectionJob || autoJob) && (
          <div className="space-y-3">
            {renderJobProgress(scanJob, 'Postfach-Scan', 'bg-sky-500')}
            {renderJobProgress(syncAllJob, 'Alle synchronisieren', 'bg-emerald-500')}
            {renderJobProgress(selectionJob, 'Auswahl synchronisieren', 'bg-emerald-400')}
            {renderJobProgress(autoJob, 'AutoSync', 'bg-emerald-300')}
          </div>
        )}

      {syncError && (
        <div className="rounded-lg border border-rose-700 bg-rose-500/10 p-4 text-sm text-rose-200">
          <p className="font-semibold">{syncError}</p>
          {missing.length > 0 && (
            <ul className="mt-2 space-y-1 text-xs">
              {missing.map((item, index) => (
                <li key={`${item.uid ?? index}-${index}`}>
                  <span className="font-semibold">{item.uid ?? 'Unbekannte UID'}:</span>{' '}
                  {item.reason ?? 'Keine Zuordnung gefunden'}
                  {(item.account_id || item.folder) && (
                    <span className="text-slate-300">{` (Konto ${
                      item.account_id ?? 'unbekannt'
                    }${item.folder ? ` · ${item.folder}` : ''})`}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {syncNotice && (
        <div className="rounded-lg border border-emerald-700 bg-emerald-500/10 p-4 text-sm text-emerald-200">
          <p className="font-semibold">{syncNotice}</p>
          {syncResult.length > 0 && (
            <div className="mt-2">
              <p>Folgende UIDs wurden exportiert:</p>
              <ul className="mt-1 list-inside list-disc text-xs">
                {syncResult.map((uid) => (
                  <li key={uid}>{uid}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {showInitialLoading && (
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-6 text-sm text-slate-300">
          Lade Termine …
        </div>
      )}

      {showEmptyState && (
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-6 text-sm text-slate-300">
          Keine Termine gefunden.
        </div>
      )}

      {!showInitialLoading && totalEvents > 0 && (
        <div className="space-y-3">
          {paginatedEvents.map((event) => {
            const isOpen = openItems.includes(event.id);
            const dateRange = formatDateRange(event);
            const sourceParts = [
              event.source_account_id ? `Konto #${event.source_account_id}` : null,
              event.source_folder,
            ].filter(Boolean);
            const conflictCount = event.conflicts?.length ?? 0;
            const syncState = event.sync_state;
            const hasSyncConflict = syncState?.has_conflict ?? false;
            const differences = syncState?.conflict_details?.differences ?? [];
            const suggestions = syncState?.conflict_details?.suggestions ?? [];
            const differencesExpanded = expandedDifferences[event.id] ?? false;
            const isSelectable = !hasSyncConflict && event.status !== 'failed';
            const historyEntries = sortHistoryEntries(event.history ?? []);
            const deletingMail = mailActionId === event.id;
            const disablingTracking = resolvingConflictId === event.id;
            return (
              <div
                key={event.id}
                className="overflow-hidden rounded-xl border border-slate-800 bg-slate-950 shadow-sm shadow-slate-900/40"
              >
                <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start sm:justify-between">
                  <div className="flex flex-1 items-start gap-3">
                    <input
                      type="checkbox"
                      className={`mt-1 h-4 w-4 rounded border-slate-600 bg-slate-950 ${
                        isSelectable ? '' : 'cursor-not-allowed opacity-50'
                      }`}
                      checked={selected.includes(event.id)}
                      onChange={() => toggleSelection(event.id)}
                      disabled={!isSelectable}
                      title={
                        isSelectable
                          ? undefined
                          : 'Synchronisation gesperrt: Konflikt muss zuerst gelöst werden.'
                      }
                    />
                    <button
                      type="button"
                      onClick={() => toggleOpen(event.id)}
                      className="mt-0.5 flex h-6 w-6 items-center justify-center rounded-full border border-slate-700 text-slate-300 transition hover:border-slate-500 hover:text-slate-100"
                      aria-label={isOpen ? 'Details schließen' : 'Details anzeigen'}
                    >
                      <span className={`text-lg transition-transform ${isOpen ? 'rotate-180' : ''}`}>
                        ▾
                      </span>
                    </button>
                    <div className="space-y-2">
                      <div className="text-sm font-semibold text-slate-100">
                        {event.summary ?? 'Unbenannter Termin'}
                      </div>
                      <p className="text-xs text-slate-400">{dateRange}</p>
                      <p className="text-xs text-slate-500">
                        {sourceParts.length > 0 ? sourceParts.join(' · ') : 'Quelle unbekannt'}
                      </p>
                    </div>
                  </div>
                  <div className="flex flex-col items-start gap-2 sm:items-end">
                    <span
                      className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${
                        statusStyleMap[event.status]
                      }`}
                    >
                      {statusLabelMap[event.status]}
                    </span>
                    <span
                      className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${
                        responseStyleMap[event.response_status]
                      }`}
                    >
                      {responseLabelMap[event.response_status]}
                    </span>
                    {conflictCount > 0 && (
                      <span className="inline-flex items-center rounded-full bg-amber-500/20 px-3 py-1 text-xs font-semibold text-amber-300">
                        {conflictCount === 1 ? '1 Konflikt' : `${conflictCount} Konflikte`}
                      </span>
                    )}
                    {hasSyncConflict && (
                      <span className="inline-flex items-center rounded-full bg-rose-500/20 px-3 py-1 text-xs font-semibold text-rose-300">
                        Sync-Konflikt
                      </span>
                    )}
                  </div>
                </div>
                {isOpen && (
                  <div className="border-t border-slate-800 bg-slate-900/70 px-4 py-4 text-sm text-slate-200">
                    <div className="grid gap-3 sm:grid-cols-2">
                      <div>
                        <p className="text-xs uppercase tracking-wide text-slate-500">Organisator</p>
                        <p className="mt-1 text-slate-200">{event.organizer ?? 'Keine Angabe'}</p>
                      </div>
                      <div>
                        <p className="text-xs uppercase tracking-wide text-slate-500">UID</p>
                        <p className="mt-1 break-all text-slate-300">{event.uid}</p>
                      </div>
                      <div>
                        <p className="text-xs uppercase tracking-wide text-slate-500">Quelle</p>
                        <p className="mt-1 text-slate-300">
                          {sourceParts.length > 0 ? sourceParts.join(' · ') : 'Keine Zuordnung'}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs uppercase tracking-wide text-slate-500">Zeitspanne</p>
                        <p className="mt-1 text-slate-300">{dateRange}</p>
                      </div>
                    </div>
                    {event.status === 'failed' && (
                      <div className="mt-4 rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-100">
                        <p className="text-sm font-semibold text-rose-200">Importfehler</p>
                        <p className="mt-1 text-rose-100/80">
                          {event.mail_error ?? 'Der Kalenderinhalt dieser E-Mail konnte nicht verarbeitet werden.'}
                        </p>
                        <p className="mt-2 text-rose-100/60">
                          Lösche die Nachricht oder schließe sie vom zukünftigen Tracking aus, um weitere Fehler zu
                          vermeiden.
                        </p>
                        <div className="mt-3 flex flex-wrap gap-2">
                          <button
                            type="button"
                            onClick={() => handleDeleteMail(event)}
                            disabled={deletingMail || disablingTracking}
                            className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition focus:outline-none focus:ring-2 focus:ring-rose-300/60 ${
                              deletingMail || disablingTracking
                                ? 'cursor-progress bg-rose-500/30 text-rose-200/80'
                                : 'bg-rose-500 text-rose-950 hover:bg-rose-400'
                            }`}
                          >
                            {deletingMail ? 'Wird gelöscht…' : 'Mail im Postfach löschen'}
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDisableTracking(event)}
                            disabled={deletingMail || disablingTracking}
                            className={`rounded-lg border px-3 py-1.5 text-xs font-semibold transition focus:outline-none focus:ring-2 focus:ring-rose-300/60 ${
                              deletingMail || disablingTracking
                                ? 'cursor-progress border-rose-400/40 text-rose-200/70'
                                : 'border-rose-400/60 text-rose-100 hover:border-rose-300 hover:bg-rose-900/40'
                            }`}
                          >
                            {disablingTracking ? 'Wird ausgeschlossen…' : 'Vom Tracking ausschließen'}
                          </button>
                        </div>
                      </div>
                    )}
                    {event.attendees.length > 0 && (
                      <div className="mt-4">
                        <p className="text-xs uppercase tracking-wide text-slate-500">Teilnehmer</p>
                        <div className="mt-2 max-h-40 overflow-y-auto pr-2">
                          <ul className="space-y-1 text-xs text-slate-300">
                            {event.attendees.map((attendee, index) => {
                              const primaryLabel = attendee.name ?? attendee.email ?? `Teilnehmer ${index + 1}`;
                              const emailLabel = attendee.name && attendee.email ? attendee.email : attendee.name ? '' : attendee.email;
                              const statusLabel = attendee.status ? attendeeStatusMap[attendee.status] ?? attendee.status : null;
                              const responseNote = attendee.response_requested ? 'Antwort erbeten' : null;
                              return (
                                <li key={`${attendee.email ?? attendee.name ?? index}`} className="rounded border border-slate-800/60 bg-slate-900/60 p-2">
                                  <span className="font-semibold text-slate-200">{primaryLabel}</span>
                                  {emailLabel && (
                                    <span className="ml-2 text-[11px] text-slate-400">{emailLabel}</span>
                                  )}
                                  <div className="mt-1 text-[11px] text-slate-400">
                                    {statusLabel ? statusLabel : 'Status unbekannt'}
                                    {responseNote ? ` · ${responseNote}` : ''}
                                    {attendee.type ? ` · ${attendee.type}` : ''}
                                  </div>
                                </li>
                              );
                            })}
                          </ul>
                        </div>
                      </div>
                    )}
                    {conflictCount > 0 && (
                      <div className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-100">
                        <p className="text-sm font-semibold text-amber-200">Terminkonflikte erkannt</p>
                        <p className="mt-1 text-amber-100/80">
                          In den verknüpften CalDAV-Daten überschneiden sich folgende Termine mit diesem Eintrag:
                        </p>
                        <ul className="mt-2 space-y-1">
                          {event.conflicts.map((conflict) => (
                            <li key={conflict.uid} className="leading-snug">
                              <span className="font-semibold text-amber-200">
                                {conflict.summary ?? conflict.uid}
                              </span>
                              <span className="block text-[11px] text-amber-100/70">
                                {formatConflictRange(conflict)}
                              </span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {hasSyncConflict && (
                      <div className="mt-4 space-y-3 rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-100">
                        <div>
                          <p className="text-sm font-semibold text-rose-200">Synchronisationskonflikt</p>
                          <p className="mt-1 text-rose-100/80">
                            {syncState?.conflict_reason ??
                              'Kalenderdaten und E-Mail-Import unterscheiden sich. Bitte Termin prüfen.'}
                          </p>
                        </div>
                        {differences.length > 0 && (
                          <div>
                            <button
                              type="button"
                              onClick={() => toggleDifferences(event.id)}
                              className="flex w-full items-center justify-between rounded-lg border border-rose-400/30 bg-rose-950/20 px-3 py-2 text-left text-xs font-semibold text-rose-200 transition hover:bg-rose-950/40 focus:outline-none focus:ring-2 focus:ring-rose-400/50"
                              aria-expanded={differencesExpanded}
                            >
                              <span>
                                Unterschiede zwischen E-Mail-Import und Kalenderdaten ({differences.length})
                              </span>
                              <span className={`text-base transition-transform ${differencesExpanded ? 'rotate-180' : ''}`}>
                                ▾
                              </span>
                            </button>
                            {differencesExpanded && (
                              <div className="mt-2 space-y-2">
                                {differences.map((difference) => {
                                  const isMerging = activeMergeId === event.id;
                                  const selection =
                                    mergeSelections[event.id]?.[difference.field] ??
                                    (difference.field === 'response_status' ? 'email' : 'calendar');
                                  return (
                                    <div
                                      key={difference.field}
                                      className="rounded-lg border border-rose-400/30 bg-rose-950/20 p-2"
                                    >
                                      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                                        <p className="text-xs font-semibold text-rose-200">{difference.label}</p>
                                        {isMerging && (
                                          <div className="flex flex-wrap gap-1 text-[11px]">
                                            <button
                                              type="button"
                                              onClick={() => updateMergeSelection(event.id, difference.field, 'email')}
                                              className={`rounded px-2 py-1 font-semibold transition ${
                                                selection === 'email'
                                                  ? 'bg-rose-400/30 text-rose-100'
                                                  : 'bg-rose-950/40 text-rose-300 hover:bg-rose-900/40'
                                              }`}
                                            >
                                              E-Mail-Import verwenden
                                            </button>
                                            <button
                                              type="button"
                                              onClick={() => updateMergeSelection(event.id, difference.field, 'calendar')}
                                              className={`rounded px-2 py-1 font-semibold transition ${
                                                selection === 'calendar'
                                                  ? 'bg-rose-400/30 text-rose-100'
                                                  : 'bg-rose-950/40 text-rose-300 hover:bg-rose-900/40'
                                              }`}
                                            >
                                              Kalenderdaten verwenden
                                            </button>
                                          </div>
                                        )}
                                      </div>
                                      <div className="mt-2 grid gap-3 text-[11px] text-rose-100/80 sm:grid-cols-2">
                                        <div
                                          className={
                                            isMerging && selection === 'email'
                                              ? 'rounded-md border border-rose-400/40 bg-rose-900/40 p-2'
                                              : 'p-0'
                                          }
                                        >
                                          <span className="font-semibold text-rose-300">E-Mail-Import</span>
                                          <p className="mt-1 whitespace-pre-wrap break-words">
                                            {formatDifferenceValue(difference, 'local')}
                                          </p>
                                        </div>
                                        <div
                                          className={
                                            isMerging && selection === 'calendar'
                                              ? 'rounded-md border border-rose-400/40 bg-rose-900/40 p-2'
                                              : 'p-0'
                                          }
                                        >
                                          <span className="font-semibold text-rose-300">Kalenderdaten</span>
                                          <p className="mt-1 whitespace-pre-wrap break-words">
                                            {formatDifferenceValue(difference, 'remote')}
                                          </p>
                                        </div>
                                      </div>
                                    </div>
                                  );
                                })}
                              </div>
                            )}
                          </div>
                        )}
                        {suggestions.length > 0 && (
                              <div>
                                <p className="text-[11px] uppercase tracking-wide text-rose-300/80">Lösungsvorschläge</p>
                                <div className="mt-2 space-y-2">
                                  {suggestions.map((suggestion) => {
                                const disableInProgress =
                                  suggestion.action === 'disable-tracking' &&
                                  resolvingConflictId === event.id;
                                const resolveInProgress =
                                  suggestion.action !== 'disable-tracking' &&
                                  suggestion.action !== 'merge-fields' &&
                                  resolvingConflictId === event.id;
                                const mergingActive =
                                  suggestion.action === 'merge-fields' && activeMergeId === event.id;
                                return (
                                  <button
                                    key={suggestion.action}
                                    type="button"
                                    onClick={() => handleSuggestionClick(event, suggestion)}
                                    disabled={disableInProgress || resolveInProgress}
                                    className={`w-full rounded-lg border border-rose-400/30 bg-rose-950/15 p-3 text-left transition focus:outline-none focus:ring-2 focus:ring-rose-400/50 ${
                                      disableInProgress || resolveInProgress
                                        ? 'cursor-progress opacity-60'
                                        : 'cursor-pointer hover:bg-rose-900/40'
                                    }`}
                                  >
                                    <p className="text-xs font-semibold text-rose-200">{suggestion.label}</p>
                                    <p className="mt-1 whitespace-pre-wrap break-words text-rose-100/80">
                                      {suggestion.description}
                                    </p>
                                    {disableInProgress && (
                                      <p className="mt-2 text-[11px] font-semibold text-rose-200">
                                        Wird entfernt…
                                      </p>
                                    )}
                                    {resolveInProgress && (
                                      <p className="mt-2 text-[11px] font-semibold text-rose-200">
                                        Lösung wird angewendet…
                                      </p>
                                    )}
                                    {mergingActive && (
                                      <p className="mt-2 text-[11px] font-semibold text-rose-200">
                                        Wähle für jedes Feld die gewünschte Quelle aus.
                                      </p>
                                    )}
                                  </button>
                                );
                              })}
                                </div>
                              {activeMergeId === event.id && (
                                <div className="mt-3 flex flex-wrap gap-2">
                                  <button
                                    type="button"
                                    onClick={() => applyMerge(event)}
                                    disabled={resolvingConflictId === event.id}
                                    className="rounded-lg bg-rose-500 px-3 py-1.5 text-xs font-semibold text-rose-50 transition hover:bg-rose-400 disabled:cursor-not-allowed disabled:opacity-60"
                                  >
                                    Auswahl übernehmen
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => resetMerge(event.id)}
                                    disabled={resolvingConflictId === event.id}
                                    className="rounded-lg border border-rose-400/40 px-3 py-1.5 text-xs font-semibold text-rose-200 transition hover:border-rose-300 hover:text-rose-100 disabled:cursor-not-allowed disabled:opacity-60"
                                  >
                                    Zusammenführung abbrechen
                                  </button>
                                </div>
                              )}
                              </div>
                        )}
                      </div>
                    )}
                    <div className="mt-4 grid gap-3 text-xs text-slate-400 sm:grid-cols-2">
                      <div>
                        <p className="uppercase tracking-wide text-slate-500">Letzte Änderung (E-Mail-Import)</p>
                        <p className="mt-1 text-slate-300">
                          {formatSyncTimestamp(syncState?.local_last_modified)}
                        </p>
                      </div>
                      <div>
                        <p className="uppercase tracking-wide text-slate-500">Letzte Änderung (Kalenderdaten)</p>
                        <p className="mt-1 text-slate-300">
                          {formatSyncTimestamp(syncState?.remote_last_modified)}
                        </p>
                      </div>
                      <div>
                        <p className="uppercase tracking-wide text-slate-500">Quelle der letzten Änderung</p>
                        <p className="mt-1 text-slate-300">
                          {syncState?.last_modified_source
                            ? syncSourceLabels[syncState.last_modified_source] ?? syncState.last_modified_source
                            : 'Keine Angabe'}
                        </p>
                      </div>
                      <div>
                        <p className="uppercase tracking-wide text-slate-500">CalDAV ETag</p>
                        <p className="mt-1 break-all text-slate-300">{syncState?.caldav_etag ?? '–'}</p>
                      </div>
                    </div>
                    <div className="mt-4">
                      <p className="text-xs uppercase tracking-wide text-slate-500">Historie</p>
                      {historyEntries.length > 0 ? (
                        <>
                          <div className="mt-2 max-h-48 overflow-y-auto pr-2">
                            <ul className="space-y-1 text-xs text-slate-300">
                              {historyEntries.map((entry, index) => {
                                const parsed = entry.timestamp ? new Date(entry.timestamp) : null;
                                const formatted =
                                  parsed && !Number.isNaN(parsed.getTime())
                                    ? parsed.toLocaleString()
                                    : 'Unbekannter Zeitpunkt';
                                return (
                                  <li key={`${entry.timestamp}-${index}`}>
                                    <span className="font-semibold text-slate-200">{formatted}:</span>{' '}
                                    {entry.description}
                                  </li>
                                );
                              })}
                            </ul>
                          </div>
                          {historyEntries.length > 10 && (
                            <p className="mt-1 text-[11px] text-slate-500">
                              Neueste Einträge zuerst – ältere Einträge per Scroll erreichbar.
                            </p>
                          )}
                        </>
                      ) : (
                        <p className="mt-2 text-xs text-slate-400">Keine Historie vorhanden.</p>
                      )}
                    </div>
                    {event.status !== 'failed' && (
                      <div className="mt-4 flex flex-wrap gap-2">
                        {responseActions.map((action) => (
                          <button
                            key={action.value}
                            type="button"
                            onClick={() => handleResponse(event, action.value)}
                            disabled={respondingId === event.id}
                            className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition disabled:opacity-60 ${
                              action.className
                            } ${
                              event.response_status === action.value
                                ? 'ring-2 ring-emerald-300/60 ring-offset-2 ring-offset-slate-900'
                                : ''
                            }`}
                          >
                            {action.label}
                          </button>
                        ))}
                        <button
                          type="button"
                          onClick={() => handleResponse(event, 'none')}
                          disabled={respondingId === event.id}
                          className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs font-semibold text-slate-200 transition hover:border-slate-500 hover:text-slate-100 disabled:opacity-60"
                        >
                          Antwort zurücksetzen
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {!showEmptyState && totalEvents > 0 && (
        <div className="flex flex-col gap-3 rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-xs text-slate-300 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <span>
              Zeige {pageStart}–{pageEnd} von {totalEvents} Terminen
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <button
              type="button"
              onClick={goToPreviousPage}
              disabled={page === 1}
              className="rounded-lg border border-slate-700 px-3 py-1 font-semibold text-slate-200 transition hover:border-emerald-400 hover:text-emerald-200 disabled:cursor-not-allowed disabled:border-slate-800 disabled:text-slate-500"
            >
              Vorherige Seite
            </button>
            <span className="px-2 py-1 text-slate-400">
              Seite {page} von {totalPages}
            </span>
            <button
              type="button"
              onClick={goToNextPage}
              disabled={page === totalPages || totalEvents === 0}
              className="rounded-lg border border-slate-700 px-3 py-1 font-semibold text-slate-200 transition hover:border-emerald-400 hover:text-emerald-200 disabled:cursor-not-allowed disabled:border-slate-800 disabled:text-slate-500"
            >
              Nächste Seite
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
