export type ConversationState = {
  pendingCandidates: string[];
  lastItemIds: string[];
  lastBranch: string | null;
};

export type Verdict = {
  status: string;
  meaning: string;
  service: string;
};

export type SessionInfo = {
  token: string;
  expiresAt: number;
  role: string;
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
  extras: { subject?: string; branch?: string; country?: string } = {},
): Promise<SessionInfo> {
  const response = await fetch(`${apiBase}/api/session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      password,
      subject: extras.subject ?? "internal",
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
    country: body.country,
    branch: body.branch,
  };
}

export async function streamChat(
  apiBase: string,
  message: string,
  state: ConversationState | null,
  token: string | null,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(`${apiBase}/api/chat/stream`, {
    method: "POST",
    headers,
    body: JSON.stringify({ message, state }),
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
  let data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (!data) return;
  const payload = JSON.parse(data) as Record<string, unknown>;
  if (event === "verdict") handlers.onVerdict(payload as Parameters<StreamHandlers["onVerdict"]>[0]);
  else if (event === "text") handlers.onText(String(payload.text ?? ""));
  else if (event === "done") handlers.onDone(payload as Parameters<StreamHandlers["onDone"]>[0]);
}

async function safeDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string };
    return body.detail ?? "";
  } catch {
    return "";
  }
}
