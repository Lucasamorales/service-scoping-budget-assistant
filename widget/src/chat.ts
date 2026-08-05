import { createSession, streamChat, type ConversationState, type SessionInfo } from "./api.js";
import { renderMarkdown, escapeHtml } from "./markdown.js";
import { readJson, removeKey, writeJson } from "./storage.js";
import { STYLES } from "./styles.js";

const SESSION_KEY = "acme.session";
const STATE_KEY = "acme.state";

const STARTERS = [
  { label: "Merch for a launch", message: "Can we order merch for a branch opening?" },
  { label: "Billboard advert", message: "Can we put an advert on a billboard?" },
  { label: "Translate web pages", message: "Can you translate our web pages into Spanish?" },
  { label: "SEO audit", message: "Do we cover an SEO audit?" },
];

const STATUS_LABEL: Record<string, string> = {
  in_scope: "In scope",
  out_of_scope: "Out of scope",
  local: "Local",
  quote_required: "Quote required",
};

class AcmeChat extends HTMLElement {
  #root: ShadowRoot;
  #apiBase: string;
  #authRequired = false;
  #session: SessionInfo | null = null;
  #state: ConversationState | null = null;
  #busy = false;
  #abort: AbortController | null = null;

  constructor() {
    super();
    this.#root = this.attachShadow({ mode: "open" });
    this.#apiBase = (this.getAttribute("api-base") || "").replace(/\/$/, "");
  }

  connectedCallback(): void {
    this.#session = readJson<SessionInfo>(SESSION_KEY);
    this.#state = readJson<ConversationState>(STATE_KEY);
    void this.#boot();
  }

  disconnectedCallback(): void {
    this.#abort?.abort();
  }

  async #boot(): Promise<void> {
    try {
      const health = await fetch(`${this.#apiBase}/api/health`).then((r) => r.json());
      this.#authRequired = Boolean(health.authRequired);
    } catch {
      this.#authRequired = false;
    }

    if (this.#authRequired && !this.#hasValidSession()) {
      this.#renderLogin();
      return;
    }
    this.#renderChat();
  }

  #hasValidSession(): boolean {
    return Boolean(this.#session?.token && this.#session.expiresAt * 1000 > Date.now());
  }

  #renderLogin(): void {
    this.#root.innerHTML = `
      <style>${STYLES}</style>
      <div class="shell">
        <form class="login" part="login">
          <div class="brand">Acme <span>Scoping</span></div>
          <h1>Sign in to ask</h1>
          <p>Internal tool for Account Managers. Enter the shared access password.</p>
          <input name="password" type="password" autocomplete="current-password" placeholder="Access password" required />
          <input name="branch" type="text" placeholder="Branch (optional)" />
          <div class="error" data-error></div>
          <button type="submit">Continue</button>
        </form>
      </div>
    `;
    const form = this.#root.querySelector("form");
    form?.addEventListener("submit", (event) => {
      event.preventDefault();
      void this.#signIn(new FormData(form as HTMLFormElement));
    });
  }

  async #signIn(data: FormData): Promise<void> {
    const error = this.#root.querySelector("[data-error]");
    if (error) error.textContent = "";
    try {
      this.#session = await createSession(this.#apiBase, String(data.get("password") || ""), {
        branch: String(data.get("branch") || "") || undefined,
      });
      writeJson(SESSION_KEY, this.#session);
      this.#renderChat();
    } catch (err) {
      if (error) error.textContent = err instanceof Error ? err.message : "Sign-in failed.";
    }
  }

  #renderChat(): void {
    this.#root.innerHTML = `
      <style>${STYLES}</style>
      <div class="shell">
        <header>
          <div class="brand">Acme <span>Scoping Assistant</span></div>
          <div class="meta">
            ${this.#session?.branch ? escapeHtml(this.#session.branch) + " · " : ""}
            <button type="button" class="secondary" data-reset>New chat</button>
          </div>
        </header>
        <div class="messages" data-messages>
          <div class="empty">
            Ask whether a marketing request is covered by central marketing, handled locally,
            refused, or needs quoting. Verdicts come from the service breakdown — not from the model guessing.
          </div>
        </div>
        <div class="starters" data-starters></div>
        <form class="composer">
          <textarea name="message" rows="1" placeholder="e.g. Can we do a billboard for the new branch?" required></textarea>
          <button type="submit" data-send>Ask</button>
        </form>
      </div>
    `;

    const starters = this.#root.querySelector("[data-starters]");
    for (const starter of STARTERS) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = starter.label;
      button.dataset.message = starter.message;
      button.addEventListener("click", () => {
        void this.#ask(starter.message);
      });
      starters?.append(button);
    }

    this.#root.querySelector("[data-reset]")?.addEventListener("click", () => {
      this.#state = null;
      removeKey(STATE_KEY);
      this.#renderChat();
    });

    const form = this.#root.querySelector("form.composer");
    const textarea = this.#root.querySelector("textarea");
    form?.addEventListener("submit", (event) => {
      event.preventDefault();
      const value = textarea instanceof HTMLTextAreaElement ? textarea.value.trim() : "";
      if (!value) return;
      if (textarea instanceof HTMLTextAreaElement) textarea.value = "";
      void this.#ask(value);
    });
    textarea?.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        (form as HTMLFormElement | null)?.requestSubmit();
      }
    });
  }

  async #ask(message: string): Promise<void> {
    if (this.#busy) return;
    this.#busy = true;
    this.#setSending(true);

    const messages = this.#root.querySelector("[data-messages]");
    const starters = this.#root.querySelector("[data-starters]");
    if (starters) starters.replaceChildren();
    messages?.querySelector(".empty")?.remove();

    this.#appendRow("user", escapeHtml(message));
    const assistant = this.#appendAssistantPlaceholder();

    this.#abort = new AbortController();
    let assembled = "";

    try {
      await streamChat(
        this.#apiBase,
        message,
        this.#state,
        this.#authRequired ? this.#session?.token ?? null : null,
        {
          onVerdict: (payload) => {
            assistant.badge.replaceChildren();
            if (payload.needsAHuman) {
              assistant.badge.append(this.#badge("handover", "Handover"));
            } else if (payload.verdict) {
              assistant.badge.append(
                this.#badge(payload.verdict.status, STATUS_LABEL[payload.verdict.status] ?? payload.verdict.status),
              );
            } else if (payload.awaitingAnswer) {
              assistant.badge.append(this.#badge("ask", "Needs clarification"));
            }
            assistant.citations.textContent = payload.citations.length
              ? `Read from ${payload.citations.join("; ")}`
              : "";
            if (payload.notes.length) {
              assistant.notes.textContent = payload.notes.join(" ");
            }
          },
          onText: (text) => {
            assembled += text;
            assistant.body.classList.remove("typing");
            assistant.body.innerHTML = renderMarkdown(assembled);
            this.#scrollToEnd();
          },
          onDone: (payload) => {
            assembled = payload.text || assembled;
            assistant.body.classList.remove("typing");
            assistant.body.innerHTML = renderMarkdown(assembled);
            this.#state = payload.state;
            writeJson(STATE_KEY, this.#state);
            if (payload.degraded) {
              assistant.notes.textContent =
                (assistant.notes.textContent ? assistant.notes.textContent + " " : "") +
                "Answered without the language model.";
            }
            if (payload.truncated) {
              assistant.notes.textContent =
                (assistant.notes.textContent ? assistant.notes.textContent + " " : "") +
                "The reply was cut short.";
            }
          },
        },
        this.#abort.signal,
      );
    } catch (err) {
      assistant.body.classList.remove("typing");
      const text = err instanceof Error ? err.message : "Something went wrong.";
      if (text.toLowerCase().includes("unauthorised")) {
        removeKey(SESSION_KEY);
        this.#session = null;
        this.#renderLogin();
        return;
      }
      assistant.body.textContent = text;
    } finally {
      this.#busy = false;
      this.#setSending(false);
      this.#scrollToEnd();
    }
  }

  #appendRow(role: "user" | "assistant", html: string): HTMLElement {
    const messages = this.#root.querySelector("[data-messages]");
    const row = document.createElement("div");
    row.className = `row ${role}`;
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.innerHTML = html;
    row.append(bubble);
    messages?.append(row);
    this.#scrollToEnd();
    return bubble;
  }

  #appendAssistantPlaceholder(): {
    badge: HTMLElement;
    body: HTMLElement;
    citations: HTMLElement;
    notes: HTMLElement;
  } {
    const bubble = this.#appendRow("assistant", "");
    const badge = document.createElement("div");
    const body = document.createElement("div");
    body.className = "typing";
    body.textContent = "Looking that up";
    const citations = document.createElement("div");
    citations.className = "citations";
    const notes = document.createElement("div");
    notes.className = "note";
    bubble.replaceChildren(badge, body, citations, notes);
    return { badge, body, citations, notes };
  }

  #badge(kind: string, label: string): HTMLElement {
    const el = document.createElement("div");
    el.className = `verdict ${kind}`;
    el.textContent = label;
    return el;
  }

  #setSending(busy: boolean): void {
    const button = this.#root.querySelector<HTMLButtonElement>("[data-send]");
    const textarea = this.#root.querySelector<HTMLTextAreaElement>("textarea");
    if (button) button.disabled = busy;
    if (textarea) textarea.disabled = busy;
  }

  #scrollToEnd(): void {
    const messages = this.#root.querySelector("[data-messages]");
    if (messages) messages.scrollTop = messages.scrollHeight;
  }
}

// Exported for tests / host pages that import the module.
export { AcmeChat, renderMarkdown, escapeHtml };

if (!customElements.get("acme-chat")) {
  customElements.define("acme-chat", AcmeChat);
}
