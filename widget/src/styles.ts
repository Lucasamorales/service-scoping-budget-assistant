/** Styles injected into the shadow root. Kept here so the host page cannot leak in. */

export const STYLES = `
:host {
  /* One palette. The assistant used to ship navy and light with a toggle in
     the header; Acme uses light, so the choice was noise on every screen for a
     decision nobody needed to make.

     These are the light values exactly as the toggle produced them, so nothing
     about the appearance changed when the switch went away. --red and --note
     were never redefined by the light override and are carried across
     unaltered for the same reason. */
  --canvas: #E4EBF2;
  --panel: #F4F7FA;
  --surface: #FFFFFF;
  --surface-alt: #F0F4F8;
  --input-bg: #FFFFFF;
  --accent: #3B6BA5;
  --red: #EE2C2C;
  --user-bg: #232F55;
  --text: #14213B;
  --body: #2C3D50;
  --text-soft: #5A6E85;
  --text-faint: #8A9BAD;
  --line: #D7E0EA;
  --hair: #E8EEF4;
  /* Not a leftover of the theme switch: New chat borders with this, and it
     sits in the navy header, so it stays a translucent white. */
  --toggle-line: rgba(255, 255, 255, 0.28);
  /* Header stays navy with white text: the light theme was never a white
     slab, and this is the band that keeps it recognisably Acme. */
  --header-bg: #232F55;
  --header-border: transparent;
  --header-text: #FFFFFF;
  --handover-bubble: #FFFFFF;
  --handover-border: #F2C2C2;
  --note: #E08A6A;
  --login-input-bg: #FFFFFF;

  --pill-in-fg: #1F7A4D;
  --pill-in-bg: #E6F5EC;
  --pill-in-bd: #A9DCC1;
  --pill-quote-fg: #1D5D8C;
  --pill-quote-bg: #E7F1F9;
  --pill-quote-bd: #A9CFE8;
  --pill-local-fg: #A6741A;
  --pill-local-bg: #FBF2E0;
  --pill-local-bd: #E4C88A;
  --pill-out-fg: #6E5A4E;
  --pill-out-bg: #F2EDE9;
  --pill-out-bd: #D8C8BC;
  --pill-ask-fg: #9A4E12;
  --pill-ask-bg: #FCEEE2;
  --pill-ask-bd: #E8BE96;

  --font-ui: "Archivo", "Segoe UI", sans-serif;
  --font-display: "Caveat Brush", "Segoe Print", cursive;

  display: block;
  color: var(--text);
  font-family: var(--font-ui);
  font-size: 15px;
  line-height: 1.45;
}

* { box-sizing: border-box; }

.frame {
  /* Holds the conversation and, when it is open, the service list beside it.
     Centred rather than stretched, so with the list closed the chat sits
     exactly where it always did instead of drifting to one edge of a wider
     container. */
  display: flex;
  justify-content: center;
  align-items: stretch;
  gap: 14px;
  width: 100%;
}

.shell {
  display: grid;
  grid-template-rows: auto 1fr auto;
  /* Anchors the context overlay, which is absolutely positioned to cover the
     whole widget. overflow: hidden below then clips it to the rounded corners
     for free. */
  position: relative;
  flex: 1 1 auto;
  min-width: 0;
  max-width: 760px;
  height: min(760px, calc(100vh - 80px));
  max-height: 100dvh;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 16px;
  overflow: hidden;
  transition: background-color 150ms ease, border-color 150ms ease;
}

header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 22px;
  background: var(--header-bg);
  border-bottom: 1px solid var(--header-border);
  color: var(--header-text);
}

/* Deliberately no text-transform. The wordmark is "Acme" — a lowercase i and
   three capitals — and uppercasing it renders the brand wrong. The letter
   spacing is what carries the wordmark look, not the case. */
.brand {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.14em;
  white-space: nowrap;
}

.brand span {
  font-weight: 400;
  opacity: 0.6;
  letter-spacing: 0.04em;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.branch {
  font-size: 12px;
  opacity: 0.6;
  white-space: nowrap;
}

button.new-chat {
  appearance: none;
  font: inherit;
  font-size: 12px;
  font-weight: 500;
  padding: 7px 13px;
  border-radius: 999px;
  border: 1px solid var(--toggle-line);
  background: transparent;
  color: inherit;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
}

button.new-chat:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 22px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 0;
}

.row {
  display: flex;
}

.row.user { justify-content: flex-end; }
.row.assistant { justify-content: flex-start; }

.row.assistant.pending .bubble-inner,
.row.assistant.pending .live-banner {
  display: none;
}

.row.assistant.pending .waiting {
  display: block;
  padding: 14px 16px;
  font-size: 15px;
  color: var(--text-soft);
}

.row.assistant:not(.pending) .waiting {
  display: none;
}

.waiting { display: none; }

.bubble {
  border-radius: 12px;
  transition: background-color 150ms ease, border-color 150ms ease;
}

.row.user .bubble {
  max-width: 74%;
  padding: 12px 16px;
  background: var(--user-bg);
  color: #FFFFFF;
  font-size: 15px;
  line-height: 1.5;
  white-space: pre-wrap;
}

.row.assistant .bubble {
  max-width: 86%;
  overflow: hidden;
  background: var(--surface);
  border: 1px solid var(--line);
  color: var(--body);
}

.row.assistant .bubble.handover {
  background: var(--handover-bubble);
  border-color: var(--handover-border);
}

.bubble-inner {
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.handover-banner {
  background: var(--red);
  color: #FFFFFF;
  padding: 9px 16px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.verdict {
  align-self: flex-start;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  padding: 5px 10px;
  border-radius: 999px;
  border: 1px solid;
}

.verdict.in_scope {
  color: var(--pill-in-fg);
  background: var(--pill-in-bg);
  border-color: var(--pill-in-bd);
}

.verdict.quote_required {
  color: var(--pill-quote-fg);
  background: var(--pill-quote-bg);
  border-color: var(--pill-quote-bd);
}

.verdict.local {
  color: var(--pill-local-fg);
  background: var(--pill-local-bg);
  border-color: var(--pill-local-bd);
}

.verdict.out_of_scope {
  color: var(--pill-out-fg);
  background: var(--pill-out-bg);
  border-color: var(--pill-out-bd);
}

.verdict.ask {
  color: var(--pill-ask-fg);
  background: var(--pill-ask-bg);
  border-color: var(--pill-ask-bd);
}

.live {
  display: flex;
  flex-direction: column;
  gap: 9px;
  align-items: flex-start;
}

.service-title {
  font-size: 15px;
  font-weight: 700;
  line-height: 1.4;
  color: var(--text);
}

.prose {
  font-size: 15px;
  line-height: 1.55;
  color: var(--body);
}

.prose p { margin: 0 0 0.65em; }
.prose p:last-child { margin-bottom: 0; }
.prose ul, .prose ol { margin: 0.4em 0; padding-left: 1.2em; }
.prose strong { font-weight: 700; color: var(--text); }

.caret {
  display: inline-block;
  width: 8px;
  height: 16px;
  margin-left: 2px;
  background: var(--accent);
  vertical-align: -3px;
  animation: blink 1s steps(1) infinite;
}

@keyframes blink {
  50% { opacity: 0; }
}

.candidates {
  display: grid;
  gap: 8px;
  margin-top: 2px;
}

.candidate {
  appearance: none;
  display: flex;
  gap: 12px;
  align-items: baseline;
  text-align: left;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: var(--surface-alt);
  color: var(--text);
  font: inherit;
  cursor: pointer;
  transition: border-color 150ms ease;
}

.candidate:hover { border-color: var(--accent); }

/* The context box. A dialog over the whole widget rather than a field below
   the reply: inline, it sat under a wall of text and people scrolled past it,
   then wondered why nothing sent. Covering the conversation makes the one
   remaining step the only thing on screen. */
/* The service list, as a drawer beside the conversation rather than over it.
   Different job from the context dialog, so deliberately a different pattern:
   that one blocks because it is a step you must finish, this one is reference
   you read while looking at the reply that raised the question. */
.catalog {
  /* Beside the conversation, not over it, so it can stay open while somebody
     keeps typing. Below CATALOG_BESIDE_MIN there is not room for both and it
     falls back to a drawer — see the media query at the end of this block. */
  flex: 0 0 340px;
  align-self: stretch;
  height: min(760px, calc(100vh - 80px));
  max-height: 100dvh;
  display: grid;
  grid-template-rows: auto 1fr;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 16px;
  overflow: hidden;
  animation: catalog-in 160ms ease-out;
}

@keyframes catalog-in {
  from { transform: translateX(12px); opacity: 0; }
  to { transform: translateX(0); opacity: 1; }
}

@media (prefers-reduced-motion: reduce) {
  .catalog { animation: none; }
}

.catalog-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--hair);
}

.catalog-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
}

.catalog-close {
  appearance: none;
  border: 1px solid var(--line);
  background: transparent;
  color: var(--text-soft);
  font: inherit;
  font-size: 18px;
  line-height: 1;
  padding: 4px 10px;
  border-radius: 999px;
  cursor: pointer;
}

.catalog-close:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.catalog-body {
  overflow-y: auto;
  padding: 10px 12px 16px;
}

.catalog-group + .catalog-group {
  margin-top: 6px;
}

.catalog-toggle {
  appearance: none;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 11px 13px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
  color: var(--text);
  font: inherit;
  font-size: 14px;
  font-weight: 600;
  text-align: left;
  cursor: pointer;
}

.catalog-toggle:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.catalog-count {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-faint);
}

/* display: flex on a class beats the browser's own [hidden] rule, so without
   this the first category renders expanded and the accordion looks broken. */
.catalog-items[hidden] {
  display: none;
}

.catalog-items {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px 4px 6px 13px;
}

.catalog-item .name {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}

.catalog-item .where {
  display: block;
  font-size: 11px;
  color: var(--text-faint);
  margin-top: 1px;
}

.catalog-item .what {
  display: block;
  font-size: 12px;
  line-height: 1.45;
  color: var(--text-soft);
  margin-top: 3px;
}

.catalog-empty {
  padding: 16px 13px;
  font-size: 13px;
  color: var(--text-soft);
}

/* The way in from the empty state, before there is a header button. */
.list-link {
  appearance: none;
  border: 0;
  padding: 0;
  background: none;
  font: inherit;
  color: var(--accent);
  font-weight: 600;
  text-decoration: underline;
  text-underline-offset: 2px;
  cursor: pointer;
}

.list-link:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

/* Not enough room for a conversation and a list side by side, so the list goes
   back to covering the chat. 1140 is 760 of conversation, 340 of list, the gap
   between them, and a little air. */
@media (max-width: 1140px) {
  .frame {
    position: relative;
  }

  .catalog {
    position: absolute;
    top: 0;
    right: 0;
    bottom: 0;
    height: auto;
    width: min(340px, 100%);
    z-index: 6;
    border-radius: 16px 0 0 16px;
    box-shadow: -14px 0 34px rgba(16, 26, 51, 0.16);
  }
}

@media (max-width: 640px) {
  .catalog {
    width: 100%;
    border-radius: 0;
  }
}

.note-overlay {
  position: absolute;
  inset: 0;
  z-index: 5;
  display: grid;
  place-items: center;
  padding: 24px;
  /* The scrim carries the dimming on its own, so a browser without
     backdrop-filter still separates the dialog from the conversation instead
     of showing it floating on unchanged text. */
  background: rgba(20, 33, 59, 0.42);
  backdrop-filter: blur(3px);
  -webkit-backdrop-filter: blur(3px);
  animation: note-in 140ms ease-out;
}

.note-card {
  width: min(420px, 100%);
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 20px;
  border-radius: 14px;
  background: var(--surface);
  border: 1px solid var(--line);
  box-shadow: 0 18px 44px rgba(16, 26, 51, 0.3);
}

@keyframes note-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

@media (prefers-reduced-motion: reduce) {
  .note-overlay { animation: none; }
}

.note-prompt {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}

.note-input {
  width: 100%;
  resize: vertical;
  min-height: 84px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: var(--input-bg);
  color: var(--text);
  font: inherit;
  font-size: 14px;
  line-height: 1.45;
}

.note-input::placeholder {
  color: var(--text-faint);
}

.note-input:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}

.note-actions {
  display: flex;
  gap: 8px;
}

.note-send[disabled] {
  opacity: 0.45;
  cursor: not-allowed;
}

.candidate:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.candidate .num {
  font-family: var(--font-display);
  font-size: 18px;
  color: var(--accent);
  transform: skewX(-6deg);
  flex-shrink: 0;
}

.candidate .label {
  font-size: 15px;
  font-weight: 700;
  line-height: 1.35;
}

.citations {
  font-size: 13px;
  color: var(--text-faint);
  padding-top: 9px;
  border-top: 1px solid var(--hair);
}

.note {
  font-size: 13px;
  color: var(--note);
}

.note:empty,
.citations:empty,
.service-title:empty,
.live:empty,
.live-banner:empty {
  display: none;
}

.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 22px;
  padding: 42px 30px 8px;
  text-align: center;
}

.empty-intro {
  margin: 0;
  max-width: 480px;
  font-size: 15px;
  line-height: 1.55;
  color: var(--text-soft);
  text-wrap: pretty;
}

.empty-headline {
  margin: 0;
  max-width: 520px;
  font-family: var(--font-display);
  font-size: 42px;
  font-weight: 400;
  line-height: 1.05;
  color: var(--text);
  transform: skewX(-6deg);
}

.empty-headline .accent { color: var(--accent); }

.cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  width: 100%;
  text-align: left;
}

.card {
  appearance: none;
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 16px 15px 18px;
  border-radius: 12px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: inherit;
  font: inherit;
  cursor: pointer;
  transition: border-color 150ms ease;
}

.card:hover { border-color: var(--accent); }

.card:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.card .num {
  font-family: var(--font-display);
  font-size: 20px;
  color: var(--accent);
  transform: skewX(-6deg);
}

.card .label {
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
}

.card .hint {
  font-size: 13px;
  line-height: 1.45;
  color: var(--text-soft);
}

.composer {
  padding: 16px 22px 22px;
  border-top: 1px solid var(--line);
}

.composer-pill {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  border-radius: 26px;
  padding: 6px 6px 6px 20px;
  background: var(--input-bg);
  border: 1px solid var(--line);
  transition: border-color 150ms ease;
}

.composer-pill:focus-within {
  border-color: var(--accent);
}

.composer textarea {
  flex: 1;
  min-width: 0;
  border: 0;
  background: transparent;
  color: var(--text);
  font: inherit;
  font-size: 15px;
  line-height: 1.4;
  padding: 13px 0;
  max-height: 96px;
  resize: none;
  outline: none;
}

.composer textarea::placeholder {
  color: var(--text-faint);
}

.composer textarea:disabled {
  opacity: 0.7;
  color: var(--text);
}

button.send {
  appearance: none;
  width: 44px;
  height: 44px;
  flex-shrink: 0;
  border: 0;
  border-radius: 999px;
  background: var(--red);
  color: #FFFFFF;
  font-size: 19px;
  line-height: 1;
  cursor: pointer;
  display: grid;
  place-items: center;
}

button.send:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

button.send:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.login-wrap {
  display: flex;
  flex-direction: column;
  min-height: min(760px, calc(100vh - 80px));
  max-height: 100dvh;
}

.login-wrap header {
  border-bottom: 0;
}

.torn {
  height: 14px;
  background: var(--surface);
  clip-path: polygon(
    0 40%, 3% 70%, 7% 35%, 12% 80%, 18% 30%, 24% 75%, 30% 40%,
    36% 85%, 42% 25%, 48% 70%, 54% 35%, 60% 80%, 66% 30%, 72% 75%,
    78% 40%, 84% 85%, 90% 30%, 95% 65%, 100% 40%, 100% 100%, 0 100%
  );
}

.login {
  display: grid;
  gap: 14px;
  max-width: 360px;
  margin: 0 auto;
  padding: 52px 40px 56px;
  width: 100%;
}

.login h1 {
  margin: 0;
  font-family: var(--font-display);
  font-size: 40px;
  font-weight: 400;
  line-height: 1.05;
  color: var(--text);
  transform: skewX(-6deg);
}

.login p {
  margin: 0;
  font-size: 15px;
  line-height: 1.5;
  color: var(--text-soft);
}

.login input {
  font: inherit;
  font-size: 15px;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: var(--login-input-bg);
  color: var(--text);
  outline: none;
}

.login input:focus-visible {
  border-color: var(--accent);
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.login button[type="submit"] {
  appearance: none;
  border: 0;
  border-radius: 10px;
  background: var(--red);
  color: #FFFFFF;
  font: inherit;
  font-size: 15px;
  font-weight: 700;
  padding: 13px;
  cursor: pointer;
}

.login button[type="submit"]:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.error {
  min-height: 1.2em;
  font-size: 13px;
  color: var(--red);
}

@media (max-width: 640px) {
  .shell,
  .login-wrap {
    height: 100dvh;
    max-height: 100dvh;
    border-radius: 0;
    border: 0;
  }

  .branch { display: none; }

  .empty {
    padding: 20px 4px 8px;
  }

  .empty-headline { font-size: 32px; }

  .cards {
    grid-template-columns: 1fr;
  }

  .row.user .bubble { max-width: 88%; }
  .row.assistant .bubble { max-width: 94%; }

  .messages { padding: 16px; }
  .composer { padding: 12px 14px 16px; }
  header { padding: 14px 16px; }
}

@media (prefers-reduced-motion: reduce) {
  .shell,
  .bubble,
  .candidate,
  .card,
  .composer-pill {
    transition: none;
  }

  .caret {
    animation: none;
  }
}
`;
