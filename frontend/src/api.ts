export type DocStatus = "pending" | "processing" | "ready" | "failed";

export interface Project {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
  document_count: number;
  conversation_count: number;
}

export interface DocumentItem {
  id: string;
  project_id: string;
  filename: string;
  content_type: string | null;
  size_bytes: number;
  status: DocStatus;
  error: string | null;
  num_chunks: number;
  created_at: string;
  updated_at: string;
}

export interface UploadResult {
  uploaded: DocumentItem[];
  skipped: { filename: string; reason: string }[];
}

export interface Source {
  index: number;
  chunk_id: number;
  document_id: string;
  filename: string;
  page: number | null;
  content: string;
  score: number;
}

export interface Conversation {
  id: string;
  project_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources: Source[] | null;
  created_at: string;
}

export interface ConversationDetail extends Conversation {
  messages: Message[];
}

export type ChatEvent =
  | { type: "sources"; sources: Source[]; query: string }
  | { type: "token"; content: string }
  | { type: "done"; message_id: string; title: string }
  | { type: "error"; error: string };

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return body.detail.map((d: { msg: string }) => d.msg).join("; ");
  } catch {
    /* not JSON */
  }
  return `${res.status} ${res.statusText}`;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const res = await fetch(path, { ...init, headers });
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res));
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const json = (body: unknown) => JSON.stringify(body);

export const api = {
  // projects
  listProjects: () => request<Project[]>("/api/projects"),
  getProject: (id: string) => request<Project>(`/api/projects/${id}`),
  createProject: (name: string, description?: string) =>
    request<Project>("/api/projects", { method: "POST", body: json({ name, description: description || null }) }),
  updateProject: (id: string, patch: { name?: string; description?: string | null }) =>
    request<Project>(`/api/projects/${id}`, { method: "PATCH", body: json(patch) }),
  deleteProject: (id: string) => request<void>(`/api/projects/${id}`, { method: "DELETE" }),

  // documents
  listDocuments: (projectId: string) => request<DocumentItem[]>(`/api/projects/${projectId}/documents`),
  deleteDocument: (id: string) => request<void>(`/api/documents/${id}`, { method: "DELETE" }),
  reprocessDocument: (id: string) => request<DocumentItem>(`/api/documents/${id}/reprocess`, { method: "POST" }),
  documentUrl: (id: string) => `/api/documents/${id}/download`,

  // conversations
  listConversations: (projectId: string) => request<Conversation[]>(`/api/projects/${projectId}/conversations`),
  createConversation: (projectId: string) =>
    request<Conversation>(`/api/projects/${projectId}/conversations`, { method: "POST", body: json({}) }),
  getConversation: (id: string) => request<ConversationDetail>(`/api/conversations/${id}`),
  renameConversation: (id: string, title: string) =>
    request<Conversation>(`/api/conversations/${id}`, { method: "PATCH", body: json({ title }) }),
  deleteConversation: (id: string) => request<void>(`/api/conversations/${id}`, { method: "DELETE" }),
};

/** Upload with progress reporting (fetch has no upload progress, so use XHR). */
export function uploadFiles(
  projectId: string,
  files: File[],
  onProgress: (fraction: number) => void,
): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f, f.name));
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/projects/${projectId}/documents`);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      let body: any = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* ignore */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as UploadResult);
      else reject(new ApiError(xhr.status, (body && body.detail) || `Upload failed (${xhr.status})`));
    };
    xhr.onerror = () => reject(new ApiError(0, "Network error during upload"));
    xhr.send(form);
  });
}

/** POST a message and consume the Server-Sent Events stream. */
export async function streamChat(
  conversationId: string,
  content: string,
  documentIds: string[] | null,
  onEvent: (e: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`/api/conversations/${conversationId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: json({ content, document_ids: documentIds && documentIds.length ? documentIds : null }),
    signal,
  });
  if (!res.ok || !res.body) throw new ApiError(res.status, await errorMessage(res));

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      const data = raw
        .split("\n")
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).trimStart())
        .join("\n");
      if (data) onEvent(JSON.parse(data) as ChatEvent);
    }
  }
}
