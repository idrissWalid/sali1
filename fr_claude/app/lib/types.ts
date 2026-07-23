export interface SourceItem {
  name: string;
  type: "tabular" | "document";
  meta: string;
}

export interface SessionItem {
  id: string;
  title: string;
  type: string;
  filename?: string;
  created_at: string;
}

export interface ChatSource {
  page: number;
  text: string;
}

export interface Message {
  role: "user" | "assistant";
  text: string;
  images?: string[];
  isSummary?: boolean;
  sources?: ChatSource[];
}

export interface UploadData {
  session_id: string;
  filename?: string;
  profile?: { filename?: string };
  type: string;
  interpretation?: string;
  summary?: string;
}

export interface UploadProgressEvent {
  status: "processing" | "error" | "clarification_needed" | "completed";
  step?: number;
  message?: string;
  data?: UploadData;
}

export interface UploadProgressState {
  active: boolean;
  fileName: string;
  step: number;
  message: string;
}

export interface ModelInfo {
  id: string;
  name: string;
  type: string;
  features: string[];
  metrics: Record<string, unknown>;
  created_at: string;
}

export interface DashboardData {
  overview: {
    n_lignes?: number;
    n_colonnes?: number;
    pct_valeurs_manquantes_total?: number;
    n_doublons?: number;
  };
  preview: Record<string, unknown>[];
  variables: Record<string, { type?: string; pct_manquantes?: number }>;
  distributions: Record<string, { type: string; data: { name: string; value: number }[] }>;
  filename: string;
}
