/** Styles injected into the shadow root. Kept here so the host page cannot leak in. */

export const STYLES = `
:host {
  --ink: #14212b;
  --ink-soft: #3d4f5c;
  --paper: #f4f7f5;
  --paper-2: #e7eee9;
  --line: #c5d2c9;
  --accent: #0b6e4f;
  --accent-ink: #073b2a;
  --warn: #9a3412;
  --danger: #8b1e1e;
  --quote: #1d4e89;
  --local: #6b4f1d;
  --out: #5c4033;
  --radius: 10px;
  --font: "IBM Plex Sans", "Segoe UI", sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, monospace;
  display: block;
  color: var(--ink);
  font-family: var(--font);
  font-size: 15px;
  line-height: 1.45;
}

* { box-sizing: border-box; }

.shell {
  display: grid;
  grid-template-rows: auto 1fr auto;
  min-height: min(720px, 100dvh);
  max-height: 100dvh;
  background:
    radial-gradient(1200px 500px at 10% -10%, #d7ebe1 0%, transparent 55%),
    linear-gradient(180deg, #f7faf8 0%, var(--paper) 40%, #eef3f0 100%);
  border: 1px solid var(--line);
  border-radius: calc(var(--radius) + 4px);
  overflow: hidden;
}

header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 1rem;
  padding: 1rem 1.25rem 0.75rem;
  border-bottom: 1px solid var(--line);
}

.brand {
  font-family: var(--mono);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  font-size: 0.78rem;
  color: var(--accent-ink);
}

.brand span { color: var(--ink-soft); font-weight: 400; }

.meta {
  font-size: 0.78rem;
  color: var(--ink-soft);
}

.messages {
  overflow-y: auto;
  padding: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
}

.row { display: flex; }
.row.user { justify-content: flex-end; }
.row.assistant { justify-content: flex-start; }

.bubble {
  max-width: min(36rem, 92%);
  padding: 0.75rem 0.9rem;
  border-radius: var(--radius);
  background: white;
  border: 1px solid var(--line);
  box-shadow: 0 1px 0 rgba(20, 33, 43, 0.04);
}

.row.user .bubble {
  background: var(--accent);
  color: white;
  border-color: transparent;
}

.verdict {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-family: var(--mono);
  font-size: 0.72rem;
  letter-spacing: 0.03em;
  text-transform: uppercase;
  padding: 0.2rem 0.5rem;
  border-radius: 999px;
  margin-bottom: 0.55rem;
  border: 1px solid currentColor;
}

.verdict.in_scope { color: var(--accent); background: #e7f6ef; }
.verdict.quote_required { color: var(--quote); background: #e8f1fa; }
.verdict.local { color: var(--local); background: #f7f0e2; }
.verdict.out_of_scope { color: var(--out); background: #f3ebe6; }
.verdict.handover { color: var(--danger); background: #f8e8e8; }
.verdict.ask { color: var(--warn); background: #fff1e8; }

.citations {
  margin-top: 0.65rem;
  font-size: 0.78rem;
  color: var(--ink-soft);
}

.note {
  margin-top: 0.45rem;
  font-size: 0.78rem;
  color: var(--warn);
}

.composer {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 0.6rem;
  padding: 0.9rem 1.25rem 1.15rem;
  border-top: 1px solid var(--line);
  background: rgba(255,255,255,0.65);
  backdrop-filter: blur(6px);
}

textarea {
  resize: none;
  min-height: 2.8rem;
  max-height: 8rem;
  padding: 0.7rem 0.8rem;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  font: inherit;
  background: white;
  color: var(--ink);
}

textarea:focus {
  outline: 2px solid color-mix(in srgb, var(--accent) 45%, white);
  border-color: var(--accent);
}

button {
  font: inherit;
  font-weight: 600;
  border: none;
  border-radius: var(--radius);
  padding: 0 1.1rem;
  background: var(--ink);
  color: white;
  cursor: pointer;
}

button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

button.secondary {
  background: transparent;
  color: var(--ink-soft);
  border: 1px solid var(--line);
  padding: 0.35rem 0.7rem;
  font-size: 0.78rem;
  font-weight: 500;
}

.starters {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  padding: 0 1.25rem 1rem;
}

.starters button {
  background: white;
  color: var(--ink);
  border: 1px solid var(--line);
  font-weight: 500;
  font-size: 0.82rem;
  padding: 0.4rem 0.7rem;
}

.login {
  display: grid;
  gap: 0.75rem;
  padding: 2.5rem 1.5rem;
  max-width: 22rem;
  margin: auto;
}

.login h1 {
  margin: 0;
  font-size: 1.35rem;
  letter-spacing: -0.02em;
}

.login p {
  margin: 0;
  color: var(--ink-soft);
  font-size: 0.92rem;
}

.login input {
  font: inherit;
  padding: 0.7rem 0.8rem;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: white;
}

.login .error {
  color: var(--danger);
  font-size: 0.85rem;
  min-height: 1.2em;
}

.empty {
  color: var(--ink-soft);
  font-size: 0.95rem;
  max-width: 28rem;
}

.typing::after {
  content: "…";
  animation: pulse 1.2s steps(3, end) infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 0.25; }
  50% { opacity: 1; }
}

@media (max-width: 640px) {
  .shell { border: none; border-radius: 0; min-height: 100dvh; }
  .bubble { max-width: 100%; }
}
`;
