async function z(d,e,t){let n=await fetch(`${d}/api/session`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({password:e,subject:t.subject,branch:t.branch??null,country:t.country??null})});if(!n.ok){let r=await E(n);throw new Error(r||"Could not sign in.")}let a=await n.json();return{token:a.token,expiresAt:a.expiresAt,role:a.role,subject:a.subject??t.subject,country:a.country,branch:a.branch}}async function j(d,e,t,n,a,r,o,i){let p={"Content-Type":"application/json"};a&&(p.Authorization=`Bearer ${a}`);let s=await fetch(`${d}/api/chat/stream`,{method:"POST",headers:p,body:JSON.stringify({message:e,state:t,history:n,note:i||null}),signal:o});if(!s.ok||!s.body){let f=await E(s);throw new Error(f||`Request failed (${s.status})`)}let l=s.body.getReader(),c=new TextDecoder,g="";for(;;){let{value:f,done:w}=await l.read();if(w)break;g+=c.decode(f,{stream:!0});let b=g.split(`

`);g=b.pop()??"";for(let u of b)N(u,r)}g.trim()&&N(g,r)}function N(d,e){let t="message",n=[];for(let o of d.split(`
`))o.startsWith("event:")?t=o.slice(6).trim():o.startsWith("data:")&&n.push(o.slice(5).replace(/^ /,""));let a=n.join(`
`);if(!a)return;let r;try{r=JSON.parse(a)}catch{return}if(t==="verdict"){let o=r,i=o.verdict;e.onVerdict({verdict:i&&typeof i=="object"?{status:m(i.status),meaning:m(i.meaning),service:m(i.service)}:null,citations:q(o.citations),notes:q(o.notes),needsAHuman:!!o.needsAHuman,awaitingAnswer:!!o.awaitingAnswer,candidates:Array.isArray(o.candidates)?o.candidates:[],actions:Array.isArray(o.actions)?o.actions:[]})}else if(t==="text"){let o=m(r.text);o&&e.onText(o)}else if(t==="done"){let o=r;e.onDone({...o,text:m(o.text),source:m(o.source)||"deterministic",degraded:!!o.degraded,truncated:!!o.truncated})}}function m(d){return typeof d!="string"||d==="[object Object]"?"":d}function q(d){return Array.isArray(d)?d.map(e=>m(e)).filter(Boolean):[]}async function E(d){try{let e=await d.json();return R(e.detail)}catch{return""}}function R(d){return typeof d=="string"?d:Array.isArray(d)?d.map(t=>{if(typeof t=="string")return t;if(t&&typeof t=="object"&&"msg"in t){let n=t.msg,a=t.loc,r=Array.isArray(a)?a.join("."):"";return typeof n=="string"?r?`${r}: ${n}`:n:""}return""}).filter(Boolean).join("; ")||"Request failed validation.":d&&typeof d=="object"?"Request failed.":""}async function B(d,e){let t={};e&&(t.Authorization=`Bearer ${e}`);let n=await fetch(`${d}/api/catalog`,{headers:t});if(!n.ok)throw new Error(await E(n));let a=await n.json();return Array.isArray(a.categories)?a.categories:[]}var O={"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"};function h(d){return d.replace(/[&<>"']/g,e=>O[e]??e)}function k(d){return h(typeof d=="string"?d:"").replace(/\*\*(.+?)\*\*/g,"<strong>$1</strong>").replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g,"<em>$1</em>").replace(/_(.+?)_/g,"<em>$1</em>").replace(/\n/g,"<br>")}function x(d){try{let e=sessionStorage.getItem(d);return e?JSON.parse(e):null}catch{return null}}function v(d,e){try{sessionStorage.setItem(d,JSON.stringify(e))}catch{}}function y(d){try{sessionStorage.removeItem(d)}catch{}}var F=`
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

/* The mark replaced the wordmark, so the typographic rules that carried it \u2014
   the tracking that stood in for a logo, and the lighter "Scoping Assistant"
   beside it \u2014 are gone with it. */
.brand {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.brand-mark {
  display: block;
  height: 28px;
  width: auto;
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
     falls back to a drawer \u2014 see the media query at the end of this block. */
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
`;var A="acme.session",S="acme.state",T="acme.history",$=12,D='<svg class="brand-mark" viewBox="46 353 2294 482" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Logo"><text x="46" y="760" font-family="sans-serif" font-weight="900" font-size="460" fill="#FFFFFF">LOGO</text></svg>',V=[{label:"Merch for a launch",message:"Can we order merch for a branch opening?"},{label:"Billboard advert",message:"Can we put an advert on a billboard?"},{label:"Venue TV screens",message:"Can we change the graphics on our venue TV screens?"}],_={in_scope:"In scope",out_of_scope:"Out of scope",local:"Local",quote_required:"Quote required"},L=class extends HTMLElement{#e;#a;#r=!1;#t=null;#i=null;#n=[];#l=null;#d=!1;#c=null;constructor(){super(),this.#e=this.attachShadow({mode:"open"}),this.#a=(this.getAttribute("api-base")||"").replace(/\/$/,"")}connectedCallback(){this.#t=x(A),this.#i=x(S),this.#n=this.#T(),this.#f()}disconnectedCallback(){this.#c?.abort()}async#f(){try{let e=await fetch(`${this.#a}/api/health`).then(t=>t.json());this.#r=!!e.authRequired}catch{this.#r=!1}if(this.#r&&!this.#b()){this.#u();return}this.#p()}#b(){return!!(this.#t?.token&&this.#t.expiresAt*1e3>Date.now())}#u(){this.#e.innerHTML=`
      <style>${F}</style>
      <div class="frame">
      <div class="shell login-wrap">
        <header>
          <div class="brand">${D}</div>
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
    `;let e=this.#e.querySelector("form");e?.addEventListener("submit",t=>{t.preventDefault(),this.#C(new FormData(e))})}async#C(e){let t=this.#e.querySelector("[data-error]");t&&(t.textContent="");let n=String(e.get("subject")||"").trim();if(n.length<2){t&&(t.textContent="Enter your name so we can log who asked.");return}try{this.#t=await z(this.#a,String(e.get("password")||""),{subject:n,branch:String(e.get("branch")||"")||void 0}),v(A,this.#t),this.#p()}catch(a){t&&(t.textContent=a instanceof Error?a.message:"Sign-in failed.")}}#p(){let e=this.#t?.branch?h(this.#t.branch):"";this.#e.innerHTML=`
      <style>${F}</style>
      <div class="frame">
      <div class="shell">
        <header>
          <div class="brand">${D}</div>
          <div class="header-actions">
            ${e?`<div class="branch">${e}</div>`:""}
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
              So \u2014 what are you trying <span class="accent">to get made?</span>
            </h2>
            <div class="cards" data-cards></div>
          </div>
        </div>
        <form class="composer">
          <div class="composer-pill">
            <textarea name="message" rows="1" placeholder="e.g. Can we do a billboard for the new branch?" required></textarea>
            <button type="submit" class="send" data-send aria-label="Send">\u2191</button>
          </div>
        </form>
      </div>
      </div>
    `;let t=this.#e.querySelector("[data-cards]");V.forEach((r,o)=>{let i=document.createElement("button");i.type="button",i.className="card",i.innerHTML=`
        <span class="num">${String(o+1).padStart(2,"0")}</span>
        <span class="label">${h(r.label)}</span>
        <span class="hint">${h(r.message)}</span>
      `,i.addEventListener("click",()=>{this.#o(r.message)}),t?.append(i)}),this.#e.querySelectorAll("[data-open-catalog]").forEach(r=>{r.addEventListener("click",()=>void this.#k())}),this.#e.querySelector("[data-reset]")?.addEventListener("click",()=>{this.#i=null,this.#n=[],y(S),y(T),this.#p()});let n=this.#e.querySelector("form.composer"),a=this.#e.querySelector("textarea");n?.addEventListener("submit",r=>{r.preventDefault();let o=a instanceof HTMLTextAreaElement?a.value.trim():"";o&&(a instanceof HTMLTextAreaElement&&(a.value="",this.#g(a)),this.#o(o))}),a?.addEventListener("keydown",r=>{r.key==="Enter"&&!r.shiftKey&&(r.preventDefault(),n?.requestSubmit())}),a?.addEventListener("input",()=>{a instanceof HTMLTextAreaElement&&this.#g(a)})}#g(e){e.style.height="auto",e.style.height=`${Math.min(e.scrollHeight,96)}px`}#x(){let e=this.#e.querySelector("[data-empty]");e&&(e.remove(),this.#e.querySelector("[data-open-catalog]")?.removeAttribute("hidden"))}async#o(e,t){if(this.#d)return;this.#d=!0,this.#m(!0),this.#x(),this.#A(t?.trim()||e);let n=this.#S();this.#c=new AbortController;let a="",r=()=>{n.body.querySelector(".caret")?.remove()},o=null,i=!1,p=()=>{!i&&o&&(this.#v(n,o),i=!0),n.row.classList.remove("pending")},s=this.#n.slice();try{await j(this.#a,e,this.#i,s,this.#r?this.#t?.token??null:null,{onVerdict:l=>{o=l},onText:l=>{a+=l,p(),n.body.innerHTML=k(a);let c=document.createElement("span");c.className="caret",c.setAttribute("aria-hidden","true"),n.body.append(c),this.#s()},onDone:l=>{typeof l.text=="string"&&l.text.length>0&&(a=l.text),p(),n.body.innerHTML=k(a),this.#i=l.state,v(S,this.#i),this.#L(e,a),l.degraded&&(n.notes.textContent=(n.notes.textContent?n.notes.textContent+" ":"")+"Answered without the language model."),l.truncated&&(n.notes.textContent=(n.notes.textContent?n.notes.textContent+" ":"")+"The reply was cut short.")}},this.#c.signal,t)}catch(l){r(),p();let c=l instanceof Error?l.message:"Something went wrong.";if(c.toLowerCase().includes("unauthorised")){y(A),this.#t=null,this.#u();return}n.body.textContent=c}finally{this.#d=!1,this.#m(!1),this.#s()}}#v(e,t){if(e.status.replaceChildren(),e.banner.replaceChildren(),e.bubble.classList.toggle("handover",t.needsAHuman),t.needsAHuman){let r=document.createElement("div");r.className="handover-banner",r.textContent="Handover to a person",e.banner.append(r)}else if(t.verdict?.status&&t.verdict.service){let r=String(t.verdict.status);e.status.append(this.#h(r,_[r]??r));let o=document.createElement("div");o.className="service-title",o.textContent=String(t.verdict.service),e.status.append(o)}else t.awaitingAnswer&&e.status.append(this.#h("ask","Needs clarification"));let n=Array.isArray(t.citations)?t.citations.filter(r=>typeof r=="string"):[];n.length&&(e.citations.textContent=`Read from ${n.join("; ")}`);let a=Array.isArray(t.notes)?t.notes.filter(r=>typeof r=="string"):[];a.length&&(e.notes.textContent=a.join(" ")),t.awaitingAnswer&&t.candidates?.length?this.#y(e.candidates,t.candidates):t.actions?.length&&this.#w(e.candidates,t.actions)}#y(e,t){e.replaceChildren(),e.className="candidates",t.forEach((n,a)=>{let r=document.createElement("button");r.type="button",r.className="candidate",r.innerHTML=`
        <span class="num">${a+1}</span>
        <span class="label">${h(n.label)}</span>
      `,r.addEventListener("click",()=>{e.querySelectorAll("button").forEach(o=>{o.disabled=!0}),this.#o(n.label)}),e.append(r)})}#w(e,t){e.replaceChildren(),e.className="candidates actions",t.forEach(n=>{if(n.kind==="link"&&n.url){let i=document.createElement("a");i.className="candidate action",i.href=n.url,i.target="_blank",i.rel="noopener noreferrer",i.textContent=n.label,e.append(i);return}let a=document.createElement("button");a.type="button",a.className="candidate action";let r=typeof n.label=="string"?n.label:"Continue",o=typeof n.message=="string"&&n.message?n.message:r;a.textContent=r,a.addEventListener("click",()=>{if(n.kind==="note"){this.#E(e,n,o);return}e.querySelectorAll("button").forEach(i=>{i.disabled=!0}),this.#o(o)}),e.append(a)})}#E(e,t,n){let a=this.#e.querySelector(".shell");if(!a)return;[...e.querySelectorAll("button")].forEach(u=>u.disabled=!0);let o=document.createElement("div");o.className="note-overlay",o.setAttribute("role","dialog"),o.setAttribute("aria-modal","true");let i=document.createElement("div");i.className="note-card";let p=document.createElement("label");p.className="note-prompt",p.id=`note-prompt-${t.id}`,p.textContent=t.prompt||"Add some context for this request",o.setAttribute("aria-labelledby",p.id);let s=document.createElement("textarea");s.className="note-input",s.rows=4,s.placeholder=t.placeholder||"",s.maxLength=1e3,p.htmlFor=s.id=`note-${t.id}`;let l=document.createElement("button");l.type="button",l.className="candidate action note-send",l.textContent="Send it",l.disabled=!0;let c=document.createElement("button");c.type="button",c.className="candidate action note-cancel",c.textContent="Cancel";let g=document.createElement("div");g.className="note-actions",g.append(l,c);let f=()=>{o.remove(),document.removeEventListener("keydown",b,!0)},w=()=>[s,l,c].filter(u=>!u.hasAttribute("disabled"));function b(u){if(u.key==="Escape"){u.preventDefault(),c.click();return}if(u.key!=="Tab")return;let C=w(),I=o.contains(document.activeElement)?o.getRootNode().activeElement:null,H=C.indexOf(I),M=u.shiftKey?H-1:H+1;(M<0||M>=C.length)&&(u.preventDefault(),C[u.shiftKey?C.length-1:0].focus())}s.addEventListener("input",()=>{l.disabled=s.value.trim().length===0}),s.addEventListener("keydown",u=>{u.key==="Enter"&&!u.shiftKey&&(u.preventDefault(),l.disabled||l.click())}),l.addEventListener("click",()=>{let u=s.value.trim();u&&(f(),this.#o(n,u))}),c.addEventListener("click",()=>{f(),this.#o("No")}),document.addEventListener("keydown",b,!0),i.append(p,s,g),o.append(i),a.append(o),s.focus()}async#k(){let e=this.#e.querySelector(".frame");if(!e||this.#e.querySelector(".catalog"))return;let t=document.createElement("aside");t.className="catalog",t.setAttribute("aria-label","Service list");let n=document.createElement("div");n.className="catalog-head";let a=document.createElement("div");a.className="catalog-title",a.textContent="What we cover";let r=document.createElement("button");r.type="button",r.className="catalog-close",r.setAttribute("aria-label","Close the service list"),r.textContent="\xD7",n.append(a,r);let o=document.createElement("div");o.className="catalog-body",o.textContent="Loading\u2026";let i=()=>{t.remove(),document.removeEventListener("keydown",p,!0)};function p(s){s.key==="Escape"&&(s.preventDefault(),i())}r.addEventListener("click",i),document.addEventListener("keydown",p,!0),t.append(n,o),e.append(t),r.focus();try{this.#l||(this.#l=await B(this.#a,this.#r?this.#t?.token??null:null)),this.#F(o,this.#l)}catch{o.replaceChildren();let s=document.createElement("p");s.className="catalog-empty",s.textContent="Couldn't load the list just now. Close this and try again.",o.append(s)}}#F(e,t){e.replaceChildren();let n=[];t.forEach(a=>{let r=document.createElement("div");r.className="catalog-group";let o=document.createElement("button");o.type="button",o.className="catalog-toggle",o.setAttribute("aria-expanded","false");let i=document.createElement("span");i.textContent=a.label;let p=document.createElement("span");p.className="catalog-count",p.textContent=String(a.count),o.append(i,p);let s=document.createElement("div");s.className="catalog-items",s.hidden=!0,a.items.forEach(l=>{let c=document.createElement("div");c.className="catalog-item",c.innerHTML=`
          <span class="name">${h(l.name)}</span>
          <span class="where">${h(l.section)}</span>
          <span class="what">${h(l.summary)}</span>
        `,s.append(c)}),o.addEventListener("click",()=>{let l=s.hidden;n.forEach(c=>{c.items.hidden=!0,c.toggle.setAttribute("aria-expanded","false")}),s.hidden=!l,o.setAttribute("aria-expanded",l?"true":"false"),l&&o.scrollIntoView({block:"nearest"})}),n.push({toggle:o,items:s}),r.append(o,s),e.append(r)})}#A(e){let t=this.#e.querySelector("[data-messages]"),n=document.createElement("div");n.className="row user";let a=document.createElement("div");a.className="bubble",a.textContent=e,n.append(a),t?.append(n),this.#s()}#S(){let e=this.#e.querySelector("[data-messages]"),t=document.createElement("div");t.className="row assistant pending";let n=document.createElement("div");n.className="bubble";let a=document.createElement("div");a.className="live-banner",a.setAttribute("aria-live","polite");let r=document.createElement("div");r.className="bubble-inner";let o=document.createElement("div");o.className="live",o.setAttribute("aria-live","polite");let i=document.createElement("div");i.className="prose";let p=document.createElement("div"),s=document.createElement("div");s.className="citations";let l=document.createElement("div");l.className="note";let c=document.createElement("div");return c.className="waiting",c.textContent="Looking that up\u2026",c.setAttribute("aria-hidden","true"),r.append(o,i,p,s,l),n.append(a,r,c),t.append(n),e?.append(t),this.#s(),{row:t,bubble:n,banner:a,status:o,body:i,candidates:p,citations:s,notes:l}}#h(e,t){let n=document.createElement("div");return n.className=`verdict ${e}`,n.textContent=t,n}#m(e){let t=this.#e.querySelector("[data-send]"),n=this.#e.querySelector("textarea");t&&(t.disabled=e),n&&(n.disabled=e)}#s(){let e=this.#e.querySelector("[data-messages]");e&&(e.scrollTop=e.scrollHeight)}#T(){let e=x(T);return Array.isArray(e)?e.filter(t=>!!t&&(t.role==="user"||t.role==="assistant")&&typeof t.content=="string"&&t.content.trim().length>0).slice(-$):[]}#L(e,t){let n=(r,o=11e3)=>r.length<=o?r:`${r.slice(0,o-1)}\u2026`,a=[...this.#n,{role:"user",content:n(e,2e3)},{role:"assistant",content:n(t)}];this.#n=a.slice(-$),v(T,this.#n)}};customElements.get("acme-chat")||customElements.define("acme-chat",L);export{L as AcmeChat,h as escapeHtml,k as renderMarkdown};
