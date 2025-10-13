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
