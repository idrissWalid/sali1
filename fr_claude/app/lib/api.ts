import type {
  ChatSource,
  DashboardData,
  ModelInfo,
  SessionItem,
  UploadProgressEvent,
} from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export interface SessionDetails {
  id: string;
  title: string;
  type: string;
  filename?: string;
  messages: { role: "user" | "assistant"; text: string; images?: string[]; sources?: ChatSource[] }[];
}

export async function listSessions(): Promise<SessionItem[]> {
  const res = await fetch(`${API_URL}/api/sessions`);
  if (!res.ok) throw new Error("Impossible de charger les sessions.");
  return res.json();
}

export async function getSession(sessionId: string): Promise<SessionDetails> {
  const res = await fetch(`${API_URL}/api/sessions/${sessionId}`);
  if (!res.ok) throw new Error("Session introuvable.");
  return res.json();
}

export async function deleteSession(sessionId: string): Promise<void> {
  await fetch(`${API_URL}/api/sessions/${sessionId}`, { method: "DELETE" });
}

export async function renameSession(sessionId: string, title: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/sessions/${sessionId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new Error("Impossible de renommer la session.");
}

export async function listLlmModels(): Promise<{ models: string[]; proprietary: string[] }> {
  const res = await fetch(`${API_URL}/api/llm-models`);
  if (!res.ok) throw new Error("Impossible de charger les modèles.");
  return res.json();
}

export async function sendChatMessage(
  sessionId: string,
  message: string,
  model: string | undefined,
  signal: AbortSignal,
  /** Appelé à chaque étape annoncée par le backend (réflexion, génération de
   *  code, recherche de passages…) pour informer l'utilisateur pendant l'attente. */
  onStep?: (step: { phase: string; message: string }) => void
): Promise<{ response: string; images: string[]; sources: ChatSource[] }> {
  const res = await fetch(`${API_URL}/api/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      message,
      ...(model?.trim() ? { model: model.trim() } : {}),
    }),
    signal,
  });
  if (!res.ok || !res.body) {
    const errText = await res.text();
    throw new Error(errText || `Erreur serveur (${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: { response: string; images: string[]; sources: ChatSource[] } | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // Une ligne complète = un événement NDJSON ; le reliquat attend la suite.
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line);
      if (event.type === "step") onStep?.({ phase: event.phase, message: event.message });
      else if (event.type === "result") result = event;
      else if (event.type === "error") throw new Error(event.message);
    }
  }

  if (!result) throw new Error("Aucune réponse reçue du serveur.");
  return { response: result.response, images: result.images ?? [], sources: result.sources ?? [] };
}

export async function transcribeAudio(blob: Blob): Promise<string> {
  const formData = new FormData();
  formData.append("file", blob, "recording.webm");
  const res = await fetch(`${API_URL}/api/audio/transcribe`, { method: "POST", body: formData });
  if (!res.ok) throw new Error("Erreur de transcription.");
  const data = await res.json();
  return data.text || "";
}

export async function* streamUpload(
  file: File,
  model?: string
): AsyncGenerator<UploadProgressEvent> {
  const formData = new FormData();
  formData.append("file", file);
  if (model?.trim()) formData.append("model", model.trim());
  formData.append("index_doc", "true");

  const res = await fetch(`${API_URL}/api/upload`, {
    method: "POST",
    headers: { accept: "application/json" },
    body: formData,
  });
  if (!res.body) throw new Error("Pas de flux de réponse reçu du serveur.");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        yield JSON.parse(line) as UploadProgressEvent;
      } catch {
        // ligne non-JSON ignorée
      }
    }
  }
}

export async function downloadReport(
  sessionId: string,
  format: "pdf" | "word",
  title: string
): Promise<Blob> {
  const res = await fetch(`${API_URL}/api/report`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      title,
      institution: "CITADEL — Ouagadougou, Burkina Faso",
      format,
    }),
  });
  if (!res.ok) throw new Error("Erreur lors de la génération du rapport.");
  return res.blob();
}

export async function listTrainedModels(sessionId: string): Promise<ModelInfo[]> {
  const res = await fetch(`${API_URL}/api/models/${sessionId}`);
  if (!res.ok) throw new Error("Erreur de récupération des modèles.");
  const data = await res.json();
  return data.models || [];
}

export async function getModelInfo(modelId: string): Promise<ModelInfo> {
  const res = await fetch(`${API_URL}/api/models/info/${modelId}`);
  if (!res.ok) throw new Error("Erreur lors de la récupération des détails du modèle.");
  return res.json();
}

export function modelDownloadUrl(modelId: string): string {
  return `${API_URL}/api/models/${modelId}/download`;
}

export async function predictModel(
  modelId: string,
  features: Record<string, string | number>
): Promise<unknown> {
  const res = await fetch(`${API_URL}/api/models/${modelId}/predict`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ features }),
  });
  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(errData.detail || "Erreur de prédiction.");
  }
  const data = await res.json();
  return data.prediction;
}

export async function getDashboardData(sessionId: string, datasetId?: string): Promise<DashboardData> {
  // `datasetId` sélectionne l'un des jeux de données de la session ; sans lui,
  // le backend renvoie le premier disponible.
  const query = datasetId ? `?dataset_id=${encodeURIComponent(datasetId)}` : "";
  const res = await fetch(`${API_URL}/api/dashboard/data/${sessionId}${query}`);
  if (!res.ok) throw new Error("Erreur lors de la récupération des données du dashboard.");
  return res.json();
}
