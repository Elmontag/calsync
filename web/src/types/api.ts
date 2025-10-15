export type AccountType = 'imap' | 'caldav';
export interface ImapFolder {
  id?: number;
  name: string;
  include_subfolders: boolean;
}

export interface Account {
  id: number;
  label: string;
  type: AccountType;
  settings: Record<string, unknown>;
  imap_folders: ImapFolder[];
  created_at: string;
  updated_at: string;
}

export interface AccountCreateInput {
  label: string;
  type: AccountType;
  settings: Record<string, unknown>;
  imap_folders: ImapFolder[];
}

export type AccountUpdateInput = AccountCreateInput;

export interface ConnectionTestRequest {
  type: AccountType;
  settings: Record<string, unknown>;
}

export interface ConnectionTestResult {
  success: boolean;
  message: string;
  details?: Record<string, unknown>;
}

export interface TrackedEvent {
  id: number;
  uid: string;
  source_account_id?: number;
  source_folder?: string;
  summary?: string;
  organizer?: string;
  start?: string;
  end?: string;
  status: 'new' | 'updated' | 'cancelled' | 'synced';
  response_status: 'none' | 'accepted' | 'tentative' | 'declined';
  history: EventHistoryEntry[];
  conflicts: CalendarConflict[];
  sync_state: EventSyncState;
  tracking_disabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface EventHistoryEntry {
  timestamp: string;
  action: string;
  description: string;
}

export interface CalendarConflict {
  uid: string;
  summary?: string;
  start?: string;
  end?: string;
}

export interface ConflictDifference {
  field: string;
  label: string;
  local_value?: string | null;
  remote_value?: string | null;
}

export interface ConflictResolutionOption {
  action: string;
  label: string;
  description: string;
  interactive?: boolean;
  requires_confirmation?: boolean;
}

export interface SyncConflictDetails {
  differences: ConflictDifference[];
  suggestions: ConflictResolutionOption[];
}

export interface EventSyncState {
  local_version: number;
  synced_version: number;
  has_conflict: boolean;
  conflict_reason?: string | null;
  local_last_modified?: string | null;
  remote_last_modified?: string | null;
  last_modified_source?: string | null;
  caldav_etag?: string | null;
  conflict_details?: SyncConflictDetails | null;
}

export interface ManualSyncRequest {
  event_ids: number[];
}

export interface ManualSyncMissingDetail {
  event_id: number;
  uid?: string;
  account_id?: number;
  folder?: string;
  reason: string;
}

export interface ManualSyncResponse {
  uploaded: string[];
  missing: ManualSyncMissingDetail[];
}

export interface SyncJobStatus {
  job_id: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  processed: number;
  total?: number | null;
  detail?: Record<string, unknown> | null;
  message?: string | null;
}

export interface SyncMapping {
  id: number;
  imap_account_id: number;
  imap_folder: string;
  caldav_account_id: number;
  calendar_url: string;
  calendar_name?: string | null;
}

export interface SyncMappingCreateInput {
  imap_account_id: number;
  imap_folder: string;
  caldav_account_id: number;
  calendar_url: string;
  calendar_name?: string | null;
}

export interface AutoSyncStatus {
  enabled: boolean;
  interval_minutes?: number;
  auto_response: 'none' | 'accepted' | 'tentative' | 'declined';
  active_job?: SyncJobStatus | null;
}

export interface CalendarInfo {
  url: string;
  name: string;
}
