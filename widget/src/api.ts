export type ConversationState = {
  pendingCandidates: string[];
  lastItemIds: string[];
  lastBranch: string | null;
  conversationId?: string | null;
  /** Server-sealed mail action. Echo it back untouched; it cannot be read or built here. */
  pendingToken?: string | null;
  activeTool?: string | null;
  budgetCountry?: string | null;
  budgetBranch?: string | null;
  budgetMonth?: string | null;
};

export type ChatAction = {
  id: string;
  label: string;
  /** `note` opens a box for context and sends it beside the confirmation. */
  kind: "message" | "link" | "note";
  message?: string | null;
  url?: string | null;
  prompt?: string | null;
  placeholder?: string | null;
};

export type Verdict = {
  status: string;
  meaning: string;
  service: string;
};

export type CandidateOption = {
  id: string;
  label: string;
};

export type HistoryMessage = {
  role: "user" | "assistant";
  content: string;
};

export type SessionInfo = {
  token: string;
  expiresAt: number;
  role: string;
  subject: string | null;
  country: string | null;
  branch: string | null;
};

export type StreamHandlers = {
  onVerdict: (payload: {
    verdict: Verdict | null;
    citations: string[];
    notes: string[];
    needsAHuman: boolean;
    awaitingAnswer: boolean;
    candidates: CandidateOption[];
    actions: ChatAction[];
  }) => void;
  onText: (text: string) => void;
  onDone: (payload: {
    text: string;
    source: string;
    degraded: boolean;
    truncated: boolean;
    state: ConversationState;
  }) => void;
};

export async function createSession(
  apiBase: string,
  password: string,
  extras: {
    subject: string;
    branch?: string;
    country?: string;
  },
): Promise<SessionInfo> {
  const response = await fetch(`${apiBase}/api/session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      password,
      subject: extras.subject,
      branch: extras.branch ?? null,
      country: extras.country ?? null,
    }),
  });
  if (!response.ok) {
    const detail = await safeDetail(response);
    throw new Error(detail || "Could not sign in.");
  }
  const body = await response.json();
  return {
    token: body.token,
    expiresAt: body.expiresAt,
    role: body.role,
    subject: body.subject ?? extras.subject,
    country: body.country,
    branch: body.branch,
  };
}

export async function streamChat(
  apiBase: string,
  message: string,
  state: ConversationState | null,
  history: HistoryMessage[],
  token: string | null,
  handlers: StreamHandlers,
  signal?: AbortSignal,
  note?: string | null,
): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(`${apiBase}/api/chat/stream`, {
    method: "POST",
    headers,
    body: JSON.stringify({ message, state, history, note: note || null }),
    signal,
  });

  if (!response.ok || !response.body) {
    const detail = await safeDetail(response);
    throw new Error(detail || `Request failed (${response.status})`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const block of parts) {
      dispatchSse(block, handlers);
    }
  }
  if (buffer.trim()) dispatchSse(buffer, handlers);
}

function dispatchSse(block: string, handlers: StreamHandlers): void {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
  }
  const data = dataLines.join("\n");
  if (!data) return;

  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(data) as Record<string, unknown>;
  } catch {
    return;
  }

  if (event === "verdict") {
    const raw = payload as Parameters<StreamHandlers["onVerdict"]>[0];
    const verdictObj = raw.verdict;
    handlers.onVerdict({
      verdict:
        verdictObj && typeof verdictObj === "object"
          ? {
              status: asText((verdictObj as Verdict).status),
              meaning: asText((verdictObj as Verdict).meaning),
              service: asText((verdictObj as Verdict).service),
            }
          : null,
      citations: asStringArray(raw.citations),
      notes: asStringArray(raw.notes),
      needsAHuman: Boolean(raw.needsAHuman),
      awaitingAnswer: Boolean(raw.awaitingAnswer),
      candidates: Array.isArray(raw.candidates) ? raw.candidates : [],
      actions: Array.isArray(raw.actions) ? raw.actions : [],
    });
  } else if (event === "text") {
    const chunk = asText(payload.text);
    if (chunk) handlers.onText(chunk);
  } else if (event === "done") {
    const done = payload as Parameters<StreamHandlers["onDone"]>[0];
    handlers.onDone({
      ...done,
      text: asText(done.text),
      source: asText(done.source) || "deterministic",
      degraded: Boolean(done.degraded),
      truncated: Boolean(done.truncated),
    });
  }
}

/** SSE / DOM must get real strings — objects render as "[object Object]". */
function asText(value: unknown): string {
  if (typeof value !== "string") return "";
  if (value === "[object Object]") return "";
  return value;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => asText(item)).filter(Boolean);
}

async function safeDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    return formatDetail(body.detail);
  } catch {
    return "";
  }
}

/** FastAPI 422 ``detail`` is often an array of objects — never pass that to Error(). */
function formatDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object" && "msg" in item) {
          const msg = (item as { msg?: unknown }).msg;
          const loc = (item as { loc?: unknown }).loc;
          const where = Array.isArray(loc) ? loc.join(".") : "";
          return typeof msg === "string" ? (where ? `${where}: ${msg}` : msg) : "";
        }
        return "";
      })
      .filter(Boolean);
    return parts.join("; ") || "Request failed validation.";
  }
  if (detail && typeof detail === "object") return "Request failed.";
  return "";
}


export type CatalogItem = {
  id: string;
  name: string;
  section: string;
  summary: string;
};

export type CatalogCategory = {
  status: string;
  label: string;
  count: number;
  items: CatalogItem[];
};

export async function fetchCatalog(
  apiBase: string,
  token: string | null,
): Promise<CatalogCategory[]> {
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`${apiBase}/api/catalog`, { headers });
  if (!response.ok) throw new Error(await safeDetail(response));
  const body = (await response.json()) as { categories?: CatalogCategory[] };
  return Array.isArray(body.categories) ? body.categories : [];
}
