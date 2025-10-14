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
}

export interface CalendarInfo {
  url: string;
  name: string;
}
