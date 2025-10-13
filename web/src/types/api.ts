export type AccountType = 'imap' | 'caldav';
export type SyncDirection = 'imap_to_caldav' | 'bidirectional';

export interface ImapFolder {
  id?: number;
  name: string;
  include_subfolders: boolean;
}

export interface Account {
  id: number;
  label: string;
  type: AccountType;
  direction: SyncDirection;
  settings: Record<string, unknown>;
  imap_folders: ImapFolder[];
  created_at: string;
  updated_at: string;
}

export interface AccountCreateInput {
  label: string;
  type: AccountType;
  direction: SyncDirection;
  settings: Record<string, unknown>;
  imap_folders: ImapFolder[];
}

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
  history: EventHistoryEntry[];
}

export interface EventHistoryEntry {
  timestamp: string;
  action: string;
  description: string;
}

export interface ManualSyncRequest {
  event_ids: number[];
  target_calendar: string;
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
}

export interface CalendarInfo {
  url: string;
  name: string;
}
