import {
  createSession,
  fetchCatalog,
  streamChat,
  type CandidateOption,
  type CatalogCategory,
  type ChatAction,
  type ConversationState,
  type HistoryMessage,
  type SessionInfo,
  type Verdict,
} from "./api.js";
import { renderMarkdown, escapeHtml } from "./markdown.js";
import { readJson, removeKey, writeJson } from "./storage.js";
import { STYLES } from "./styles.js";

const SESSION_KEY = "acme.session";
const STATE_KEY = "acme.state";
const HISTORY_KEY = "acme.history";
const MAX_HISTORY = 12;

/** The Acme lockup, inlined rather than fetched.
 *
 * One request fewer, no cache-busting to remember, and no asset to serve
 * across origins from the Webflow embed.
 *
 * Colours are the artwork's own — a red mark beside a white wordmark — so
 * this is a knockout lockup and only works on a dark ground. The header band
 * is navy in the one theme this ships, which is why it belongs there and
 * nowhere else. A light header would erase the wordmark entirely.
 *
 * The viewBox is tightened to the artwork. The supplied file carries width
 * and height but no viewBox at all, so as-is it cannot scale, and the
 * lockup occupies 2294x482 of a 2454x1395 canvas.
 */
const BRAND_MARK = `<svg class="brand-mark" viewBox="46 353 2294 482" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Logo"><text x="46" y="760" font-family="sans-serif" font-weight="900" font-size="460" fill="#FFFFFF">LOGO</text></svg>`;

/* Three openers, chosen to land three different answers rather than three
   variations of the same one: two that need quoting and one that is already
   covered. The third used to be "translate our web pages", which asks a
   clarifying question instead of answering — a poor first thing to show
   somebody, and it demonstrated nothing the first two did not.

   "Graphics" rather than "assets", though stakeholders said assets. Asked with
   that word the assistant asks which service is meant, and it is right to: an
   asset on a screen is a still graphic, which is covered, or a video, which is
   chargeable. Correct behaviour, wrong thing to greet somebody with. */
const STARTERS = [
  { label: "Merch for a launch", message: "Can we order merch for a branch opening?" },
  { label: "Billboard advert", message: "Can we put an advert on a billboard?" },
  {
    label: "Venue TV screens",
    message: "Can we change the graphics on our venue TV screens?",
  },
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
  #history: HistoryMessage[] = [];
  #catalog: CatalogCategory[] | null = null;
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
    this.#history = this.#loadHistory();
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
      <div class="frame">
      <div class="shell login-wrap">
        <header>
          <div class="brand">${BRAND_MARK}</div>
        </header>
        <div class="torn" aria-hidden="true"></div>
        <form class="login" part="login">
          <h1>Sign in to ask</h1>
          <p>Internal tool for Account Managers. Enter your name and the shared access password.</p>
          <input name="subject" type="text" autocomplete="name" placeholder="Your name" required minlength="2" />
          <input name="password" type="password" autocomplete="current-password" placeholder="Access password" required />
          <input name="branch" type="text" placeholder="Branch (optional)" />
          <div class="error" data-error></div>
          <button type="submit">Continue</button>
        </form>
      </div>
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
    const subject = String(data.get("subject") || "").trim();
    if (subject.length < 2) {
      if (error) error.textContent = "Enter your name so we can log who asked.";
      return;
    }
    try {
      this.#session = await createSession(this.#apiBase, String(data.get("password") || ""), {
        subject,
        branch: String(data.get("branch") || "") || undefined,
      });
      writeJson(SESSION_KEY, this.#session);
      this.#renderChat();
    } catch (err) {
      if (error) error.textContent = err instanceof Error ? err.message : "Sign-in failed.";
    }
  }

  #renderChat(): void {
    const branch = this.#session?.branch ? escapeHtml(this.#session.branch) : "";
    this.#root.innerHTML = `
      <style>${STYLES}</style>
      <div class="frame">
      <div class="shell">
        <header>
          <div class="brand">${BRAND_MARK}</div>
          <div class="header-actions">
            ${branch ? `<div class="branch">${branch}</div>` : ""}
            <button type="button" class="new-chat" data-open-catalog hidden>Services</button>
            <button type="button" class="new-chat" data-reset>New chat</button>
          </div>
        </header>
        <div class="messages" data-messages role="log">
          <div class="empty" data-empty>
            <p class="empty-intro">
              Central marketing covers a lot of
              <button type="button" class="list-link" data-open-catalog>the list</button>,
              and not all of it. Ask before you brief, and you will know in one turn whether a job
              is covered, handled locally, out of scope, or needs a quote.
            </p>
            <h2 class="empty-headline">
              So — what are you trying <span class="accent">to get made?</span>
            </h2>
            <div class="cards" data-cards></div>
          </div>
        </div>
        <form class="composer">
          <div class="composer-pill">
            <textarea name="message" rows="1" placeholder="e.g. Can we do a billboard for the new branch?" required></textarea>
            <button type="submit" class="send" data-send aria-label="Send">↑</button>
          </div>
        </form>
      </div>
      </div>
    `;

    const cards = this.#root.querySelector("[data-cards]");
    STARTERS.forEach((starter, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "card";
      button.innerHTML = `
        <span class="num">${String(index + 1).padStart(2, "0")}</span>
        <span class="label">${escapeHtml(starter.label)}</span>
        <span class="hint">${escapeHtml(starter.message)}</span>
      `;
      button.addEventListener("click", () => {
        void this.#ask(starter.message);
      });
      cards?.append(button);
    });

    this.#root.querySelectorAll("[data-open-catalog]").forEach((el) => {
      el.addEventListener("click", () => void this.#openCatalog());
    });

    this.#root.querySelector("[data-reset]")?.addEventListener("click", () => {
      this.#state = null;
      this.#history = [];
      removeKey(STATE_KEY);
      removeKey(HISTORY_KEY);
      this.#renderChat();
    });

    const form = this.#root.querySelector("form.composer");
    const textarea = this.#root.querySelector("textarea");
    form?.addEventListener("submit", (event) => {
      event.preventDefault();
      const value = textarea instanceof HTMLTextAreaElement ? textarea.value.trim() : "";
      if (!value) return;
      if (textarea instanceof HTMLTextAreaElement) {
        textarea.value = "";
        this.#autogrow(textarea);
      }
      void this.#ask(value);
    });
    textarea?.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        (form as HTMLFormElement | null)?.requestSubmit();
      }
    });
    textarea?.addEventListener("input", () => {
      if (textarea instanceof HTMLTextAreaElement) this.#autogrow(textarea);
    });
  }

  #autogrow(textarea: HTMLTextAreaElement): void {
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 96)}px`;
  }

  #clearEmpty(): void {
    const empty = this.#root.querySelector("[data-empty]");
    if (!empty) return;
    empty.remove();
    // The link lived in the text that just disappeared, so the header takes
    // over. Hidden until now on purpose: two ways in on an empty screen is a
    // choice nobody needs to make.
    this.#root.querySelector("[data-open-catalog]")?.removeAttribute("hidden");
  }

  async #ask(message: string, note?: string): Promise<void> {
    if (this.#busy) return;
    this.#busy = true;
    this.#expireOffers();
    this.#setSending(true);
    this.#clearEmpty();
    // The context, not the bare "Yes", because that is what the person
    // actually wrote and what the recipient will read.
    this.#appendUser(note?.trim() || message);
    const assistant = this.#appendAssistantPlaceholder();

    this.#abort = new AbortController();
    let assembled = "";
    // The caret lives in the DOM, not in a closure variable. Every onText
    // rewrites body.innerHTML, which detaches it anyway, so holding a
    // reference bought nothing — and it cost a type error: TypeScript cannot
    // see the stream callbacks run, so by the catch block it had narrowed the
    // variable back to its null initialiser and the optional call landed on
    // never. Asking the DOM is both simpler and the actual source of truth.
    const dropCaret = (): void => {
      assistant.body.querySelector(".caret")?.remove();
    };
    type VerdictPayload = {
      verdict: Verdict | null;
      citations: string[];
      notes: string[];
      needsAHuman: boolean;
      awaitingAnswer: boolean;
      candidates: CandidateOption[];
      actions: ChatAction[];
    };
    let verdictPayload: VerdictPayload | null = null;
    let chromeApplied = false;

    const reveal = () => {
      if (!chromeApplied && verdictPayload) {
        this.#applyVerdictChrome(assistant, verdictPayload);
        chromeApplied = true;
      }
      assistant.row.classList.remove("pending");
    };

    const priorHistory = this.#history.slice();

    try {
      await streamChat(
        this.#apiBase,
        message,
        this.#state,
        priorHistory,
        this.#authRequired ? this.#session?.token ?? null : null,
        {
          onVerdict: (payload) => {
            verdictPayload = payload;
          },
          onText: (text) => {
            assembled += text;
            reveal();
            assistant.body.innerHTML = renderMarkdown(assembled);
            const caret = document.createElement("span");
            caret.className = "caret";
            caret.setAttribute("aria-hidden", "true");
            assistant.body.append(caret);
            this.#scrollToEnd();
          },
          onDone: (payload) => {
            if (typeof payload.text === "string" && payload.text.length > 0) {
              assembled = payload.text;
            }
            reveal();
            assistant.body.innerHTML = renderMarkdown(assembled);
            this.#state = payload.state;
            writeJson(STATE_KEY, this.#state);
            this.#appendHistory(message, assembled);
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
        note,
      );
    } catch (err) {
      dropCaret();
      reveal();
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

  #applyVerdictChrome(
    assistant: {
      bubble: HTMLElement;
      banner: HTMLElement;
      status: HTMLElement;
      candidates: HTMLElement;
      citations: HTMLElement;
      notes: HTMLElement;
    },
    payload: {
      verdict: Verdict | null;
      citations: string[];
      notes: string[];
      needsAHuman: boolean;
      awaitingAnswer: boolean;
      candidates: CandidateOption[];
      actions: ChatAction[];
    },
  ): void {
    assistant.status.replaceChildren();
    assistant.banner.replaceChildren();
    assistant.bubble.classList.toggle("handover", payload.needsAHuman);

    if (payload.needsAHuman) {
      const banner = document.createElement("div");
      banner.className = "handover-banner";
      banner.textContent = "Handover to a person";
      assistant.banner.append(banner);
    } else if (payload.verdict?.status && payload.verdict.service) {
      const statusKey = String(payload.verdict.status);
      assistant.status.append(
        this.#pill(statusKey, STATUS_LABEL[statusKey] ?? statusKey),
      );
      const title = document.createElement("div");
      title.className = "service-title";
      title.textContent = String(payload.verdict.service);
      assistant.status.append(title);
    } else if (payload.awaitingAnswer) {
      assistant.status.append(this.#pill("ask", "Needs clarification"));
    }

    const citations = Array.isArray(payload.citations)
      ? payload.citations
          .filter((item): item is string => typeof item === "string")
          .map((item) => item.trim())
          .filter(Boolean)
      : [];
    if (citations.length) {
      // Rendered exactly as sent. This used to prefix "Read from " and join on
      // semicolons, which turned a shortlist of service names into a sentence.
      // Now each line is a whole sentence composed on the server — what the
      // documentation says the matched item is, and where a figure came from —
      // so a prefix here would only make them ungrammatical.
      assistant.citations.textContent = citations.join(" ");
    }
    const notes = Array.isArray(payload.notes)
      ? payload.notes.filter((item): item is string => typeof item === "string")
      : [];
    if (notes.length) {
      assistant.notes.textContent = notes.join(" ");
    }

    if (payload.awaitingAnswer && payload.candidates?.length) {
      this.#renderCandidates(assistant.candidates, payload.candidates);
    } else if (payload.actions?.length) {
      this.#renderActions(assistant.candidates, payload.actions);
    }
  }

  #renderCandidates(
    host: HTMLElement,
    candidates: { id: string; label: string }[],
  ): void {
    host.replaceChildren();
    host.className = "candidates";
    candidates.forEach((candidate, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "candidate";
      button.innerHTML = `
        <span class="num">${index + 1}</span>
        <span class="label">${escapeHtml(candidate.label)}</span>
      `;
      button.addEventListener("click", () => {
        host.querySelectorAll("button").forEach((el) => {
          (el as HTMLButtonElement).disabled = true;
        });
        void this.#ask(candidate.label);
      });
      host.append(button);
    });
  }

  /** Retire the offers left on earlier turns before sending a new message.
   *
   * A "Yes, request a PO" button does not carry what it is agreeing to. The
   * service and the amount live in a sealed token held in the widget's state,
   * the server keeps exactly one of those at a time, and each new turn
   * replaces it. So the Yes still sitting under a 350 pound video quote would
   * raise a PO for whatever was asked about after it — a real email, to a
   * budget holder, for the wrong thing, with no error anywhere.
   *
   * Nothing is lost by retiring them: an offer that is still live is re-sent
   * with the new turn and arrives with its own buttons.
   *
   * A row whose buttons are already disabled was used rather than superseded —
   * the person clicked Yes or No, or opened the context box — so it keeps its
   * own outcome and says nothing about expiry.
   */
  #expireOffers(): void {
    this.#root.querySelectorAll(".candidates.actions").forEach((row) => {
      const buttons = [...row.querySelectorAll("button")] as HTMLButtonElement[];
      if (!buttons.length || buttons.every((el) => el.disabled)) return;
      buttons.forEach((el) => (el.disabled = true));
      const expired = document.createElement("p");
      expired.className = "actions-expired";
      expired.textContent = "No longer current — ask again if you still need it.";
      row.append(expired);
    });
  }

  #renderActions(host: HTMLElement, actions: ChatAction[]): void {
    host.replaceChildren();
    host.className = "candidates actions";
    actions.forEach((action) => {
      if (action.kind === "link" && action.url) {
        const link = document.createElement("a");
        link.className = "candidate action";
        link.href = action.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = action.label;
        host.append(link);
        return;
      }
      const button = document.createElement("button");
      button.type = "button";
      button.className = "candidate action";
      const label = typeof action.label === "string" ? action.label : "Continue";
      const message =
        typeof action.message === "string" && action.message
          ? action.message
          : label;
      button.textContent = label;
      button.addEventListener("click", () => {
        if (action.kind === "note") {
          this.#openNoteBox(host, action, message);
          return;
        }
        host.querySelectorAll("button").forEach((el) => {
          (el as HTMLButtonElement).disabled = true;
        });
        void this.#ask(message);
      });
      host.append(button);
    });
  }

  /** Ask for context before sending, and refuse to send without it.
   *
   * A dialog over the whole widget, not a field under the reply. Inline it sat
   * below a wall of text and got scrolled past, which left people waiting for
   * an email that was still waiting on them.
   *
   * The server enforces the same requirement — this is the fast half of it, so
   * nobody makes a round trip to be told they left the box empty.
   */
  #openNoteBox(host: HTMLElement, action: ChatAction, message: string): void {
    const shell = this.#root.querySelector(".shell");
    if (!shell) return;

    // Nothing behind the dialog stays clickable, so a stray Yes cannot race the
    // one the dialog is about to send.
    const behind = [...host.querySelectorAll("button")] as HTMLButtonElement[];
    behind.forEach((el) => (el.disabled = true));

    const overlay = document.createElement("div");
    overlay.className = "note-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");

    const card = document.createElement("div");
    card.className = "note-card";

    const label = document.createElement("label");
    label.className = "note-prompt";
    label.id = `note-prompt-${action.id}`;
    label.textContent = action.prompt || "Add some context for this request";
    overlay.setAttribute("aria-labelledby", label.id);

    const field = document.createElement("textarea");
    field.className = "note-input";
    field.rows = 4;
    field.placeholder = action.placeholder || "";
    field.maxLength = 1000;
    label.htmlFor = field.id = `note-${action.id}`;

    const send = document.createElement("button");
    send.type = "button";
    send.className = "candidate action note-send";
    send.textContent = "Send it";
    send.disabled = true;

    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "candidate action note-cancel";
    cancel.textContent = "Cancel";

    const row = document.createElement("div");
    row.className = "note-actions";
    row.append(send, cancel);

    const close = (): void => {
      overlay.remove();
      document.removeEventListener("keydown", onKey, true);
    };

    const focusables = (): HTMLElement[] =>
      [field, send, cancel].filter((el) => !el.hasAttribute("disabled"));

    function onKey(event: KeyboardEvent): void {
      if (event.key === "Escape") {
        event.preventDefault();
        cancel.click();
        return;
      }
      if (event.key !== "Tab") return;
      // Keep focus inside the dialog. Without this, tabbing walks onto the
      // disabled conversation behind it and the caret disappears.
      const items = focusables();
      const active = overlay.contains(document.activeElement)
        ? (overlay.getRootNode() as ShadowRoot).activeElement
        : null;
      const index = items.indexOf(active as HTMLElement);
      const next = event.shiftKey ? index - 1 : index + 1;
      if (next < 0 || next >= items.length) {
        event.preventDefault();
        items[event.shiftKey ? items.length - 1 : 0].focus();
      }
    }

    field.addEventListener("input", () => {
      send.disabled = field.value.trim().length === 0;
    });
    field.addEventListener("keydown", (event) => {
      // Enter sends, Shift+Enter breaks the line. A note is a sentence, and
      // reaching for the mouse to send one is friction.
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        if (!send.disabled) send.click();
      }
    });
    send.addEventListener("click", () => {
      const note = field.value.trim();
      if (!note) return;
      close();
      void this.#ask(message, note);
    });
    cancel.addEventListener("click", () => {
      close();
      void this.#ask("No");
    });
    document.addEventListener("keydown", onKey, true);

    card.append(label, field, row);
    overlay.append(card);
    shell.append(overlay);
    field.focus();
  }

  /** The service list, as a drawer beside the conversation.
   *
   * Grouped by verdict rather than by section, because that is the question it
   * answers — what is covered, what costs, what is ours. Grouping that way also
   * means an item needs no badge: the heading it sits under is the verdict.
   */
  async #openCatalog(): Promise<void> {
    const frame = this.#root.querySelector(".frame");
    if (!frame || this.#root.querySelector(".catalog")) return;

    const panel = document.createElement("aside");
    panel.className = "catalog";
    panel.setAttribute("aria-label", "Service list");

    const head = document.createElement("div");
    head.className = "catalog-head";
    const title = document.createElement("div");
    title.className = "catalog-title";
    title.textContent = "What we cover";
    const close = document.createElement("button");
    close.type = "button";
    close.className = "catalog-close";
    close.setAttribute("aria-label", "Close the service list");
    close.textContent = "×";
    head.append(title, close);

    const body = document.createElement("div");
    body.className = "catalog-body";
    body.textContent = "Loading…";

    const dismiss = (): void => {
      panel.remove();
      document.removeEventListener("keydown", onKey, true);
    };
    function onKey(event: KeyboardEvent): void {
      if (event.key === "Escape") {
        event.preventDefault();
        dismiss();
      }
    }
    close.addEventListener("click", dismiss);
    document.addEventListener("keydown", onKey, true);

    panel.append(head, body);
    frame.append(panel);
    close.focus();

    try {
      if (!this.#catalog) {
        this.#catalog = await fetchCatalog(
          this.#apiBase,
          this.#authRequired ? this.#session?.token ?? null : null,
        );
      }
      this.#renderCatalog(body, this.#catalog);
    } catch {
      body.replaceChildren();
      const message = document.createElement("p");
      message.className = "catalog-empty";
      message.textContent = "Couldn't load the list just now. Close this and try again.";
      body.append(message);
    }
  }

  #renderCatalog(host: HTMLElement, categories: CatalogCategory[]): void {
    host.replaceChildren();
    const groups: { toggle: HTMLButtonElement; items: HTMLElement }[] = [];

    categories.forEach((category) => {
      const group = document.createElement("div");
      group.className = "catalog-group";

      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "catalog-toggle";
      toggle.setAttribute("aria-expanded", "false");
      const label = document.createElement("span");
      label.textContent = category.label;
      const count = document.createElement("span");
      count.className = "catalog-count";
      count.textContent = String(category.count);
      toggle.append(label, count);

      const items = document.createElement("div");
      items.className = "catalog-items";
      items.hidden = true;
      category.items.forEach((item) => {
        const row = document.createElement("div");
        row.className = "catalog-item";
        row.innerHTML = `
          <span class="name">${escapeHtml(item.name)}</span>
          <span class="where">${escapeHtml(item.section)}</span>
          <span class="what">${escapeHtml(item.summary)}</span>
        `;
        items.append(row);
      });

      toggle.addEventListener("click", () => {
        const opening = items.hidden;
        // One at a time. Four categories open at once is 89 services in a
        // column, which is the wall this panel exists to replace.
        groups.forEach((other) => {
          other.items.hidden = true;
          other.toggle.setAttribute("aria-expanded", "false");
        });
        items.hidden = !opening;
        toggle.setAttribute("aria-expanded", opening ? "true" : "false");
        if (opening) toggle.scrollIntoView({ block: "nearest" });
      });

      groups.push({ toggle, items });
      group.append(toggle, items);
      host.append(group);
    });
  }

  #appendUser(message: string): void {
    const messages = this.#root.querySelector("[data-messages]");
    const row = document.createElement("div");
    row.className = "row user";
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = message;
    row.append(bubble);
    messages?.append(row);
    this.#scrollToEnd();
  }

  #appendAssistantPlaceholder(): {
    row: HTMLElement;
    bubble: HTMLElement;
    banner: HTMLElement;
    status: HTMLElement;
    body: HTMLElement;
    candidates: HTMLElement;
    citations: HTMLElement;
    notes: HTMLElement;
  } {
    const messages = this.#root.querySelector("[data-messages]");
    const row = document.createElement("div");
    row.className = "row assistant pending";

    const bubble = document.createElement("div");
    bubble.className = "bubble";

    const banner = document.createElement("div");
    banner.className = "live-banner";
    banner.setAttribute("aria-live", "polite");

    const inner = document.createElement("div");
    inner.className = "bubble-inner";

    const status = document.createElement("div");
    status.className = "live";
    status.setAttribute("aria-live", "polite");

    const body = document.createElement("div");
    body.className = "prose";

    const candidates = document.createElement("div");
    const citations = document.createElement("div");
    citations.className = "citations";
    const notes = document.createElement("div");
    notes.className = "note";

    const waiting = document.createElement("div");
    waiting.className = "waiting";
    waiting.textContent = "Looking that up…";
    waiting.setAttribute("aria-hidden", "true");

    inner.append(status, body, candidates, citations, notes);
    bubble.append(banner, inner, waiting);
    row.append(bubble);
    messages?.append(row);
    this.#scrollToEnd();

    return { row, bubble, banner, status, body, candidates, citations, notes };
  }

  #pill(kind: string, label: string): HTMLElement {
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

  #loadHistory(): HistoryMessage[] {
    const raw = readJson<HistoryMessage[]>(HISTORY_KEY);
    if (!Array.isArray(raw)) return [];
    return raw
      .filter(
        (entry): entry is HistoryMessage =>
          Boolean(entry) &&
          (entry.role === "user" || entry.role === "assistant") &&
          typeof entry.content === "string" &&
          entry.content.trim().length > 0,
      )
      .slice(-MAX_HISTORY);
  }

  #appendHistory(userMessage: string, assistantText: string): void {
    // Keep under the API history cap so a long catalogue reply does not 422
    // the next turn (that used to surface as "[object Object]" in the UI).
    const clip = (text: string, max = 11_000) =>
      text.length <= max ? text : `${text.slice(0, max - 1)}…`;
    const next: HistoryMessage[] = [
      ...this.#history,
      { role: "user", content: clip(userMessage, 2000) },
      { role: "assistant", content: clip(assistantText) },
    ];
    this.#history = next.slice(-MAX_HISTORY);
    writeJson(HISTORY_KEY, this.#history);
  }
}

export { AcmeChat, renderMarkdown, escapeHtml };

if (!customElements.get("acme-chat")) {
  customElements.define("acme-chat", AcmeChat);
}
