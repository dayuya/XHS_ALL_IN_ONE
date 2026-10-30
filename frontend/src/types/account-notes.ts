export type NoteMetric = "views" | "likes" | "collects" | "comments" | "shares";

export type NoteAccount = {
  account_id: number;
  nickname: string;
  avatar_url: string;
  account_types: string[];
  login_status: string;
  total_notes: number;
  current_notes: number;
  missing_notes: number;
  totals: Record<NoteMetric, number | null>;
  metric_note_counts: Record<NoteMetric, number>;
  sync_status: string;
  sync_source: string;
  sync_message: string;
  last_attempt_at: string | null;
  synced_at: string | null;
};

export type ManagedAccountNote = {
  id: number;
  note_id: string;
  title: string;
  cover_url: string;
  note_url: string;
  media_type: string;
  platform_status: string;
  platform_status_code: string | null;
  published_at: string | null;
  source: string;
  in_latest_sync: boolean;
  synced_at: string;
} & Record<NoteMetric, number | null>;

export type AccountNotesQuery = {
  q?: string;
  media_type?: "all" | "image" | "video";
  presence?: "all" | "current" | "missing";
  sort_by?: "published_at" | NoteMetric;
  page?: number;
  page_size?: number;
};

export type AccountNotesResponse = {
  items: ManagedAccountNote[];
  total: number;
  page: number;
  page_size: number;
  account: NoteAccount;
};
