async function D(d,e,t){let n=await fetch(`${d}/api/session`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({password:e,subject:t.subject,branch:t.branch??null,country:t.country??null})});if(!n.ok){let r=await F(n);throw new Error(r||"Could not sign in.")}let o=await n.json();return{token:o.token,expiresAt:o.expiresAt,role:o.role,subject:o.subject??t.subject,country:o.country,branch:o.branch}}async function $(d,e,t,n,o,r,a,i){let s={"Content-Type":"application/json"};o&&(s.Authorization=`Bearer ${o}`);let l=await fetch(`${d}/api/chat/stream`,{method:"POST",headers:s,body:JSON.stringify({message:e,state:t,history:n,note:i||null}),signal:a});if(!l.ok||!l.body){let h=await F(l);throw new Error(h||`Request failed (${l.status})`)}let c=l.body.getReader(),p=new TextDecoder,f="";for(;;){let{value:h,done:g}=await c.read();if(g)break;f+=p.decode(h,{stream:!0});let b=f.split(`

`);f=b.pop()??"";for(let u of b)z(u,r)}f.trim()&&z(f,r)}function z(d,e){let t="message",n=[];for(let a of d.split(`
`))a.startsWith("event:")?t=a.slice(6).trim():a.startsWith("data:")&&n.push(a.slice(5).replace(/^ /,""));let o=n.join(`
`);if(!o)return;let r;try{r=JSON.parse(o)}catch{return}if(t==="verdict"){let a=r,i=a.verdict;e.onVerdict({verdict:i&&typeof i=="object"?{status:v(i.status),meaning:v(i.meaning),service:v(i.service)}:null,citations:B(a.citations),notes:B(a.notes),needsAHuman:!!a.needsAHuman,awaitingAnswer:!!a.awaitingAnswer,candidates:Array.isArray(a.candidates)?a.candidates:[],actions:Array.isArray(a.actions)?a.actions:[]})}else if(t==="text"){let a=v(r.text);a&&e.onText(a)}else if(t==="done"){let a=r;e.onDone({...a,text:v(a.text),source:v(a.source)||"deterministic",degraded:!!a.degraded,truncated:!!a.truncated})}}function v(d){return typeof d!="string"||d==="[object Object]"?"":d}function B(d){return Array.isArray(d)?d.map(e=>v(e)).filter(Boolean):[]}async function F(d){try{let e=await d.json();return _(e.detail)}catch{return""}}function _(d){return typeof d=="string"?d:Array.isArray(d)?d.map(t=>{if(typeof t=="string")return t;if(t&&typeof t=="object"&&"msg"in t){let n=t.msg,o=t.loc,r=Array.isArray(o)?o.join("."):"";return typeof n=="string"?r?`${r}: ${n}`:n:""}return""}).filter(Boolean).join("; ")||"Request failed validation.":d&&typeof d=="object"?"Request failed.":""}async function j(d,e){let t={};e&&(t.Authorization=`Bearer ${e}`);let n=await fetch(`${d}/api/catalog`,{headers:t});if(!n.ok)throw new Error(await F(n));let o=await n.json();return Array.isArray(o.categories)?o.categories:[]}var V={"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"};function y(d){return d.replace(/[&<>"']/g,e=>V[e]??e)}function A(d){return y(typeof d=="string"?d:"").replace(/\*\*(.+?)\*\*/g,"<strong>$1</strong>").replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g,"<em>$1</em>").replace(/_(.+?)_/g,"<em>$1</em>").replace(/\n/g,"<br>")}function w(d){try{let e=sessionStorage.getItem(d);return e?JSON.parse(e):null}catch{return null}}function E(d,e){try{sessionStorage.setItem(d,JSON.stringify(e))}catch{}}function k(d){try{sessionStorage.removeItem(d)}catch{}}var S=`
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

  /* The brand faces, served from this origin \u2014 see widget/assets/fonts.css,
     which the host page has to link because font loading is document-scoped
     and cannot reach into a shadow root.

     Fallbacks are real rather than decorative: a licence problem or a failed
     request leaves a working interface in a system sans, not a broken one. */
  --font-ui: "Inter", "Segoe UI", system-ui, sans-serif;
  --font-display: "Inter Display", "Inter", "Segoe UI", sans-serif;

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

/* Two buttons in the navy band, deliberately unequal.

   Both used to be the same transparent pill with a translucent border, which
   made the one that ends a conversation look exactly like the one that opens a
   reference panel, and neither read as a control at a glance against the navy. */
button.header-button {
  appearance: none;
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  padding: 8px 15px;
  border-radius: 999px;
  /* A brighter edge and a little fill, so it sits on the band rather than
     dissolving into it. Still clearly the quieter of the two. */
  border: 1px solid rgba(255, 255, 255, 0.55);
  background: rgba(255, 255, 255, 0.1);
  color: #FFFFFF;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
  transition: background-color 150ms ease, border-color 150ms ease;
}

button.header-button:hover {
  background: rgba(255, 255, 255, 0.18);
  border-color: #FFFFFF;
}

/* New chat carries the brand red and no border: it is the one that throws work
   away, so it should be the button somebody finds without looking. */
button.header-button.primary {
  background: var(--red);
  border-color: var(--red);
}

button.header-button.primary:hover {
  background: #D8262F;
  border-color: #D8262F;
}

button.header-button:focus-visible {
  outline: 2px solid #FFFFFF;
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

/* A used or retired offer. Without this a disabled Yes looked exactly like a
   live one, which is the whole failure the expiry is there to prevent. */
.candidate:disabled {
  opacity: 0.5;
  cursor: default;
}

.candidate:disabled:hover { border-color: var(--line); }

.actions-expired {
  margin: 0;
  font-size: 13px;
  color: var(--text-faint);
}

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
  grid-template-rows: auto auto 1fr;
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

.catalog-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.catalog-search-toggle {
  appearance: none;
  border: 1px solid var(--line);
  background: transparent;
  color: var(--text-soft);
  padding: 5px 9px;
  border-radius: 999px;
  cursor: pointer;
  display: grid;
  place-items: center;
  transition: background-color 150ms ease, color 150ms ease, border-color 150ms ease;
}

.catalog-search-toggle svg {
  width: 15px;
  height: 15px;
  display: block;
}

.catalog-search-toggle:hover { border-color: var(--accent); color: var(--accent); }

/* Held down while the field is open, so the button reads as a state rather
   than as something that did nothing the second time it was pressed. */
.catalog-search-toggle.on {
  background: var(--accent);
  border-color: var(--accent);
  color: #FFFFFF;
}

.catalog-search-toggle:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.catalog-search-toggle:disabled { opacity: 0.4; cursor: not-allowed; }

/* Same trap as .catalog-items: display on the class beats the browser's own
   [hidden] rule, so without this the field is open before it is asked for. */
.catalog-search[hidden] { display: none; }

.catalog-search {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--hair);
  background: var(--surface);
}

.catalog-search-input {
  flex: 1;
  min-width: 0;
  appearance: none;
  font: inherit;
  font-size: 13px;
  padding: 8px 12px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--input-bg);
  color: var(--text);
}

.catalog-search-input::placeholder { color: var(--text-faint); }

.catalog-search-input:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}

.catalog-tally {
  font-size: 11px;
  color: var(--text-faint);
  white-space: nowrap;
  flex-shrink: 0;
}

.catalog-body {
  overflow-y: auto;
  padding: 10px 12px 16px;
}

.catalog-group[hidden] { display: none; }

.catalog-item[hidden] { display: none; }

.catalog-item mark {
  background: #FDF0C6;
  color: inherit;
  border-radius: 2px;
  padding: 0 1px;
}

.catalog-empty[hidden] { display: none; }

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
  line-height: 1.5;
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

.send-icon {
  width: 19px;
  height: 19px;
  display: block;
  /* Nudged off-centre: the plane's mass sits to its left, so a circle that
     centres the box looks like it leans. */
  margin-left: 1px;
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
`;var T="acme.session",L="acme.state",H="acme.history",I=12,O='<svg class="brand-mark" viewBox="46 353 2294 482" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Logo"><text x="46" y="760" font-family="sans-serif" font-weight="900" font-size="460" fill="#FFFFFF">LOGO</text></svg>',P='<svg class="send-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M3.3 20.7 21.5 12 3.3 3.3 3.3 10.1 15.4 12 3.3 13.9Z" fill="currentColor"/></svg>',K='<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.4 15.4 21 21"/></svg>',Y=[{label:"Merch for a launch",message:"Can we order merch for a branch opening?"},{label:"Billboard advert",message:"Can we put an advert on a billboard?"},{label:"Venue TV screens",message:"Can we change the graphics on our venue TV screens?"}],Z={in_scope:"In scope",out_of_scope:"Out of scope",local:"Local",quote_required:"Quote required"},N=class extends HTMLElement{#e;#o;#r=!1;#t=null;#i=null;#n=[];#s=null;#c=!1;#d=null;constructor(){super(),this.#e=this.attachShadow({mode:"open"}),this.#o=(this.getAttribute("api-base")||"").replace(/\/$/,"")}connectedCallback(){this.#t=w(T),this.#i=w(L),this.#n=this.#L(),this.#f()}disconnectedCallback(){this.#d?.abort()}async#f(){try{let e=await fetch(`${this.#o}/api/health`).then(t=>t.json());this.#r=!!e.authRequired}catch{this.#r=!1}if(this.#r&&!this.#b()){this.#u();return}this.#p()}#b(){return!!(this.#t?.token&&this.#t.expiresAt*1e3>Date.now())}#u(){this.#e.innerHTML=`
      <style>${S}</style>
      <div class="frame">
      <div class="shell login-wrap">
        <header>
          <div class="brand">${O}</div>
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
    `;let e=this.#e.querySelector("form");e?.addEventListener("submit",t=>{t.preventDefault(),this.#x(new FormData(e))})}async#x(e){let t=this.#e.querySelector("[data-error]");t&&(t.textContent="");let n=String(e.get("subject")||"").trim();if(n.length<2){t&&(t.textContent="Enter your name so we can log who asked.");return}try{this.#t=await D(this.#o,String(e.get("password")||""),{subject:n,branch:String(e.get("branch")||"")||void 0}),E(T,this.#t),this.#p()}catch(o){t&&(t.textContent=o instanceof Error?o.message:"Sign-in failed.")}}#p(){let e=this.#t?.branch?y(this.#t.branch):"";this.#e.innerHTML=`
      <style>${S}</style>
      <div class="frame">
      <div class="shell">
        <header>
          <div class="brand">${O}</div>
          <div class="header-actions">
            ${e?`<div class="branch">${e}</div>`:""}
            <button type="button" class="header-button" data-open-catalog hidden>Services</button>
            <button type="button" class="header-button primary" data-reset>New chat</button>
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
              What do you <span class="accent">need making?</span>
            </h2>
            <div class="cards" data-cards></div>
          </div>
        </div>
        <form class="composer">
          <div class="composer-pill">
            <textarea name="message" rows="1" placeholder="Can't find what you need? Type it here." required></textarea>
            <button type="submit" class="send" data-send aria-label="Send">${P}</button>
          </div>
        </form>
      </div>
      </div>
    `;let t=this.#e.querySelector("[data-cards]");Y.forEach((r,a)=>{let i=document.createElement("button");i.type="button",i.className="card",i.innerHTML=`
        <span class="num">${String(a+1).padStart(2,"0")}</span>
        <span class="label">${y(r.label)}</span>
        <span class="hint">${y(r.message)}</span>
      `,i.addEventListener("click",()=>{this.#a(r.message)}),t?.append(i)}),this.#e.querySelectorAll("[data-open-catalog]").forEach(r=>{r.addEventListener("click",()=>void this.#F())}),this.#e.querySelector("[data-reset]")?.addEventListener("click",()=>{this.#i=null,this.#n=[],k(L),k(H),this.#p()});let n=this.#e.querySelector("form.composer"),o=this.#e.querySelector("textarea");n?.addEventListener("submit",r=>{r.preventDefault();let a=o instanceof HTMLTextAreaElement?o.value.trim():"";a&&(o instanceof HTMLTextAreaElement&&(o.value="",this.#h(o)),this.#a(a))}),o?.addEventListener("keydown",r=>{r.key==="Enter"&&!r.shiftKey&&(r.preventDefault(),n?.requestSubmit())}),o?.addEventListener("input",()=>{o instanceof HTMLTextAreaElement&&this.#h(o)})}#h(e){e.style.height="auto",e.style.height=`${Math.min(e.scrollHeight,96)}px`}#C(){let e=this.#e.querySelector("[data-empty]");e&&(e.remove(),this.#e.querySelector("[data-open-catalog]")?.removeAttribute("hidden"))}async#a(e,t){if(this.#c)return;this.#c=!0,this.#w(),this.#m(!0),this.#C(),this.#S(t?.trim()||e);let n=this.#T();this.#d=new AbortController;let o="",r=()=>{n.body.querySelector(".caret")?.remove()},a=null,i=!1,s=()=>{!i&&a&&(this.#v(n,a),i=!0),n.row.classList.remove("pending")},l=this.#n.slice();try{await $(this.#o,e,this.#i,l,this.#r?this.#t?.token??null:null,{onVerdict:c=>{a=c},onText:c=>{o+=c,s(),n.body.innerHTML=A(o);let p=document.createElement("span");p.className="caret",p.setAttribute("aria-hidden","true"),n.body.append(p),this.#l()},onDone:c=>{typeof c.text=="string"&&c.text.length>0&&(o=c.text),s(),n.body.innerHTML=A(o),this.#i=c.state,E(L,this.#i),this.#H(e,o),c.degraded&&(n.notes.textContent=(n.notes.textContent?n.notes.textContent+" ":"")+"Answered without the language model."),c.truncated&&(n.notes.textContent=(n.notes.textContent?n.notes.textContent+" ":"")+"The reply was cut short.")}},this.#d.signal,t)}catch(c){r(),s();let p=c instanceof Error?c.message:"Something went wrong.";if(p.toLowerCase().includes("unauthorised")){k(T),this.#t=null,this.#u();return}n.body.textContent=p}finally{this.#c=!1,this.#m(!1),this.#l()}}#v(e,t){if(e.status.replaceChildren(),e.banner.replaceChildren(),e.bubble.classList.toggle("handover",t.needsAHuman),t.needsAHuman){let r=document.createElement("div");r.className="handover-banner",r.textContent="Handover to a person",e.banner.append(r)}else if(t.verdict?.status&&t.verdict.service){let r=String(t.verdict.status);e.status.append(this.#g(r,Z[r]??r));let a=document.createElement("div");a.className="service-title",a.textContent=String(t.verdict.service),e.status.append(a)}else t.awaitingAnswer&&e.status.append(this.#g("ask","Needs clarification"));let n=Array.isArray(t.citations)?t.citations.filter(r=>typeof r=="string").map(r=>r.trim()).filter(Boolean):[];n.length&&(e.citations.textContent=n.join(" "));let o=Array.isArray(t.notes)?t.notes.filter(r=>typeof r=="string"):[];o.length&&(e.notes.textContent=o.join(" ")),t.awaitingAnswer&&t.candidates?.length?this.#y(e.candidates,t.candidates):t.actions?.length&&this.#E(e.candidates,t.actions)}#y(e,t){e.replaceChildren(),e.className="candidates",t.forEach((n,o)=>{let r=document.createElement("button");r.type="button",r.className="candidate",r.innerHTML=`
        <span class="num">${o+1}</span>
        <span class="label">${y(n.label)}</span>
      `,r.addEventListener("click",()=>{e.querySelectorAll("button").forEach(a=>{a.disabled=!0}),this.#a(n.label)}),e.append(r)})}#w(){this.#e.querySelectorAll(".candidates.actions").forEach(e=>{let t=[...e.querySelectorAll("button")];if(!t.length||t.every(o=>o.disabled))return;t.forEach(o=>o.disabled=!0);let n=document.createElement("p");n.className="actions-expired",n.textContent="No longer current \u2014 ask again if you still need it.",e.append(n)})}#E(e,t){e.replaceChildren(),e.className="candidates actions",t.forEach(n=>{if(n.kind==="link"&&n.url){let i=document.createElement("a");i.className="candidate action",i.href=n.url,i.target="_blank",i.rel="noopener noreferrer",i.textContent=n.label,e.append(i);return}let o=document.createElement("button");o.type="button",o.className="candidate action";let r=typeof n.label=="string"?n.label:"Continue",a=typeof n.message=="string"&&n.message?n.message:r;o.textContent=r,o.addEventListener("click",()=>{if(n.kind==="note"){this.#k(e,n,a);return}e.querySelectorAll("button").forEach(i=>{i.disabled=!0}),this.#a(a)}),e.append(o)})}#k(e,t,n){let o=this.#e.querySelector(".shell");if(!o)return;[...e.querySelectorAll("button")].forEach(u=>u.disabled=!0);let a=document.createElement("div");a.className="note-overlay",a.setAttribute("role","dialog"),a.setAttribute("aria-modal","true");let i=document.createElement("div");i.className="note-card";let s=document.createElement("label");s.className="note-prompt",s.id=`note-prompt-${t.id}`,s.textContent=t.prompt||"Add some context for this request",a.setAttribute("aria-labelledby",s.id);let l=document.createElement("textarea");l.className="note-input",l.rows=4,l.placeholder=t.placeholder||"",l.maxLength=1e3,s.htmlFor=l.id=`note-${t.id}`;let c=document.createElement("button");c.type="button",c.className="candidate action note-send",c.textContent="Send it",c.disabled=!0;let p=document.createElement("button");p.type="button",p.className="candidate action note-cancel",p.textContent="Cancel";let f=document.createElement("div");f.className="note-actions",f.append(c,p);let h=()=>{a.remove(),document.removeEventListener("keydown",b,!0)},g=()=>[l,c,p].filter(u=>!u.hasAttribute("disabled"));function b(u){if(u.key==="Escape"){u.preventDefault(),p.click();return}if(u.key!=="Tab")return;let x=g(),m=a.contains(document.activeElement)?a.getRootNode().activeElement:null,C=x.indexOf(m),q=u.shiftKey?C-1:C+1;(q<0||q>=x.length)&&(u.preventDefault(),x[u.shiftKey?x.length-1:0].focus())}l.addEventListener("input",()=>{c.disabled=l.value.trim().length===0}),l.addEventListener("keydown",u=>{u.key==="Enter"&&!u.shiftKey&&(u.preventDefault(),c.disabled||c.click())}),c.addEventListener("click",()=>{let u=l.value.trim();u&&(h(),this.#a(n,u))}),p.addEventListener("click",()=>{h(),this.#a("No")}),document.addEventListener("keydown",b,!0),i.append(s,l,f),a.append(i),o.append(a),l.focus()}async#F(){let e=this.#e.querySelector(".frame");if(!e||this.#e.querySelector(".catalog"))return;let t=document.createElement("aside");t.className="catalog",t.setAttribute("aria-label","Service list");let n=document.createElement("div");n.className="catalog-head";let o=document.createElement("div");o.className="catalog-title",o.textContent="What we cover";let r=document.createElement("button");r.type="button",r.className="catalog-search-toggle",r.setAttribute("aria-label","Search the service list"),r.setAttribute("aria-expanded","false"),r.innerHTML=K;let a=document.createElement("button");a.type="button",a.className="catalog-close",a.setAttribute("aria-label","Close the service list"),a.textContent="\xD7";let i=document.createElement("div");i.className="catalog-actions",i.append(r,a),n.append(o,i);let s=document.createElement("div");s.className="catalog-search",s.hidden=!0;let l=document.createElement("input");l.type="search",l.className="catalog-search-input",l.placeholder="Search services",l.setAttribute("aria-label","Search the service list");let c=document.createElement("div");c.className="catalog-tally",s.append(l,c);let p=document.createElement("div");p.className="catalog-body",p.textContent="Loading\u2026";let f=null,h=()=>this.#s?.reduce((m,C)=>m+C.count,0)??0,g=()=>{let m=l.value.trim(),C=f?f(m):0;if(!m){c.textContent="";return}c.textContent=C===0?"Nothing matches that":`${C} of ${h()}`},b=m=>{s.hidden=!m,r.setAttribute("aria-expanded",m?"true":"false"),r.classList.toggle("on",m),m?l.focus():(l.value="",g())};r.addEventListener("click",()=>b(s.hidden)),l.addEventListener("input",g);let u=()=>{t.remove(),document.removeEventListener("keydown",x,!0)};function x(m){if(m.key==="Escape"){if(m.preventDefault(),!s.hidden&&l.value){l.value="",g(),l.focus();return}if(!s.hidden){b(!1),r.focus();return}u()}}a.addEventListener("click",u),document.addEventListener("keydown",x,!0),t.append(n,s,p),e.append(t),a.focus();try{this.#s||(this.#s=await j(this.#o,this.#r?this.#t?.token??null:null)),f=this.#A(p,this.#s)}catch{p.replaceChildren();let m=document.createElement("p");m.className="catalog-empty",m.textContent="Couldn't load the list just now. Close this and try again.",p.append(m),r.disabled=!0}}#A(e,t){e.replaceChildren();let n=[],o=!1,r=document.createElement("p");return r.className="catalog-empty",r.hidden=!0,r.textContent="No service matches that. Try a shorter word, or ask in the chat and I'll check.",t.forEach(a=>{let i=document.createElement("div");i.className="catalog-group";let s=document.createElement("button");s.type="button",s.className="catalog-toggle",s.setAttribute("aria-expanded","false");let l=document.createElement("span");l.textContent=a.label;let c=document.createElement("span");c.className="catalog-count",c.textContent=String(a.count),s.append(l,c);let p=document.createElement("div");p.className="catalog-items",p.hidden=!0;let f=a.items.map(h=>{let g=document.createElement("div");return g.className="catalog-item",R(g,h,[]),p.append(g),{row:g,item:h,haystack:`${h.name} ${h.section} ${h.summary}`.toLowerCase()}});s.addEventListener("click",()=>{let h=p.hidden;o||n.forEach(g=>{g.items.hidden=!0,g.toggle.setAttribute("aria-expanded","false")}),p.hidden=!h,s.setAttribute("aria-expanded",h?"true":"false"),h&&s.scrollIntoView({block:"nearest"})}),n.push({group:i,toggle:s,items:p,count:c,total:a.count,rows:f}),i.append(s,p),e.append(i)}),e.append(r),a=>{let i=a.toLowerCase().split(/\s+/).filter(Boolean);o=i.length>0;let s=0;return n.forEach(l=>{let c=0;l.rows.forEach(({row:p,item:f,haystack:h})=>{let g=!o||i.every(b=>h.includes(b));p.hidden=!g,g&&(c+=1,R(p,f,i))}),s+=c,l.group.hidden=o&&c===0,l.count.textContent=o?`${c} of ${l.total}`:String(l.total),l.items.hidden=o?c===0:!0,l.toggle.setAttribute("aria-expanded",o&&c>0?"true":"false")}),r.hidden=!o||s>0,o&&(e.scrollTop=0),s}}#S(e){let t=this.#e.querySelector("[data-messages]"),n=document.createElement("div");n.className="row user";let o=document.createElement("div");o.className="bubble",o.textContent=e,n.append(o),t?.append(n),this.#l()}#T(){let e=this.#e.querySelector("[data-messages]"),t=document.createElement("div");t.className="row assistant pending";let n=document.createElement("div");n.className="bubble";let o=document.createElement("div");o.className="live-banner",o.setAttribute("aria-live","polite");let r=document.createElement("div");r.className="bubble-inner";let a=document.createElement("div");a.className="live",a.setAttribute("aria-live","polite");let i=document.createElement("div");i.className="prose";let s=document.createElement("div"),l=document.createElement("div");l.className="citations";let c=document.createElement("div");c.className="note";let p=document.createElement("div");return p.className="waiting",p.textContent="Looking that up\u2026",p.setAttribute("aria-hidden","true"),r.append(a,i,s,l,c),n.append(o,r,p),t.append(n),e?.append(t),this.#l(),{row:t,bubble:n,banner:o,status:a,body:i,candidates:s,citations:l,notes:c}}#g(e,t){let n=document.createElement("div");return n.className=`verdict ${e}`,n.textContent=t,n}#m(e){let t=this.#e.querySelector("[data-send]"),n=this.#e.querySelector("textarea");t&&(t.disabled=e),n&&(n.disabled=e)}#l(){let e=this.#e.querySelector("[data-messages]");e&&(e.scrollTop=e.scrollHeight)}#L(){let e=w(H);return Array.isArray(e)?e.filter(t=>!!t&&(t.role==="user"||t.role==="assistant")&&typeof t.content=="string"&&t.content.trim().length>0).slice(-I):[]}#H(e,t){let n=(r,a=11e3)=>r.length<=a?r:`${r.slice(0,a-1)}\u2026`,o=[...this.#n,{role:"user",content:n(e,2e3)},{role:"assistant",content:n(t)}];this.#n=o.slice(-I),E(H,this.#n)}};function R(d,e,t){d.replaceChildren(M("name",e.name,t),M("where",e.section,t),M("what",e.summary,t))}function M(d,e,t){let n=document.createElement("span");return n.className=d,n.append(J(e,t)),n}function J(d,e){let t=document.createDocumentFragment(),n=[];if(e.length){let a=d.toLowerCase();e.forEach(i=>{for(let s=a.indexOf(i);s!==-1;s=a.indexOf(i,s+i.length))n.push([s,s+i.length])})}if(!n.length)return t.append(d),t;n.sort((a,i)=>a[0]-i[0]);let o=[];n.forEach(([a,i])=>{let s=o.at(-1);s&&a<=s[1]?s[1]=Math.max(s[1],i):o.push([a,i])});let r=0;return o.forEach(([a,i])=>{a>r&&t.append(d.slice(r,a));let s=document.createElement("mark");s.textContent=d.slice(a,i),t.append(s),r=i}),r<d.length&&t.append(d.slice(r)),t}customElements.get("acme-chat")||customElements.define("acme-chat",N);export{N as AcmeChat,y as escapeHtml,A as renderMarkdown};
