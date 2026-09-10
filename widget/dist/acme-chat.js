async function T(s,e,t){let n=await fetch(`${s}/api/session`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({password:e,subject:t.subject,branch:t.branch??null,country:t.country??null})});if(!n.ok){let r=await L(n);throw new Error(r||"Could not sign in.")}let o=await n.json();return{token:o.token,expiresAt:o.expiresAt,role:o.role,subject:o.subject??t.subject,country:o.country,branch:o.branch}}async function H(s,e,t,n,o,r,i,a){let c={"Content-Type":"application/json"};o&&(c.Authorization=`Bearer ${o}`);let d=await fetch(`${s}/api/chat/stream`,{method:"POST",headers:c,body:JSON.stringify({message:e,state:t,history:n,note:a||null}),signal:i});if(!d.ok||!d.body){let x=await L(d);throw new Error(x||`Request failed (${d.status})`)}let l=d.body.getReader(),p=new TextDecoder,h="";for(;;){let{value:x,done:N}=await l.read();if(N)break;h+=p.decode(x,{stream:!0});let S=h.split(`

`);h=S.pop()??"";for(let q of S)C(q,r)}h.trim()&&C(h,r)}function C(s,e){let t="message",n=[];for(let i of s.split(`
`))i.startsWith("event:")?t=i.slice(6).trim():i.startsWith("data:")&&n.push(i.slice(5).replace(/^ /,""));let o=n.join(`
`);if(!o)return;let r;try{r=JSON.parse(o)}catch{return}if(t==="verdict"){let i=r,a=i.verdict;e.onVerdict({verdict:a&&typeof a=="object"?{status:u(a.status),meaning:u(a.meaning),service:u(a.service)}:null,citations:F(i.citations),notes:F(i.notes),needsAHuman:!!i.needsAHuman,awaitingAnswer:!!i.awaitingAnswer,candidates:Array.isArray(i.candidates)?i.candidates:[],actions:Array.isArray(i.actions)?i.actions:[]})}else if(t==="text"){let i=u(r.text);i&&e.onText(i)}else if(t==="done"){let i=r;e.onDone({...i,text:u(i.text),source:u(i.source)||"deterministic",degraded:!!i.degraded,truncated:!!i.truncated})}}function u(s){return typeof s!="string"||s==="[object Object]"?"":s}function F(s){return Array.isArray(s)?s.map(e=>u(e)).filter(Boolean):[]}async function L(s){try{let e=await s.json();return z(e.detail)}catch{return""}}function z(s){return typeof s=="string"?s:Array.isArray(s)?s.map(t=>{if(typeof t=="string")return t;if(t&&typeof t=="object"&&"msg"in t){let n=t.msg,o=t.loc,r=Array.isArray(o)?o.join("."):"";return typeof n=="string"?r?`${r}: ${n}`:n:""}return""}).filter(Boolean).join("; ")||"Request failed validation.":s&&typeof s=="object"?"Request failed.":""}var j={"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"};function g(s){return s.replace(/[&<>"']/g,e=>j[e]??e)}function v(s){return g(typeof s=="string"?s:"").replace(/\*\*(.+?)\*\*/g,"<strong>$1</strong>").replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g,"<em>$1</em>").replace(/_(.+?)_/g,"<em>$1</em>").replace(/\n/g,"<br>")}function m(s){try{let e=sessionStorage.getItem(s);return e?JSON.parse(e):null}catch{return null}}function b(s,e){try{sessionStorage.setItem(s,JSON.stringify(e))}catch{}}function f(s){try{sessionStorage.removeItem(s)}catch{}}var y=`
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

.shell {
  display: grid;
  grid-template-rows: auto 1fr auto;
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

/* Deliberately no text-transform. The wordmark is "Acme" \u2014 a lowercase i and
   three capitals \u2014 and uppercasing it renders the brand wrong. The letter
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

/* The context box, offered under a reply that can send an email. Sits where
   the Yes/No pair was, because it replaces that decision rather than adding to
   it: there is no way to send without filling it in. */
.note-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 10px;
}

.note-prompt {
  font-size: 13px;
  font-weight: 600;
  color: var(--body);
}

.note-input {
  width: 100%;
  resize: vertical;
  min-height: 68px;
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
`;var w="acme.session",E="acme.state",k="acme.history",M=12,B=[{label:"Merch for a launch",message:"Can we order merch for a branch opening?"},{label:"Billboard advert",message:"Can we put an advert on a billboard?"},{label:"Translate web pages",message:"Can you translate our web pages into Spanish?"}],$={in_scope:"In scope",out_of_scope:"Out of scope",local:"Local",quote_required:"Quote required"},A=class extends HTMLElement{#e;#o;#a=!1;#t=null;#i=null;#n=[];#l=!1;#d=null;constructor(){super(),this.#e=this.attachShadow({mode:"open"}),this.#o=(this.getAttribute("api-base")||"").replace(/\/$/,"")}connectedCallback(){this.#t=m(w),this.#i=m(E),this.#n=this.#S(),this.#m()}disconnectedCallback(){this.#d?.abort()}async#m(){try{let e=await fetch(`${this.#o}/api/health`).then(t=>t.json());this.#a=!!e.authRequired}catch{this.#a=!1}if(this.#a&&!this.#b()){this.#p();return}this.#c()}#b(){return!!(this.#t?.token&&this.#t.expiresAt*1e3>Date.now())}#p(){this.#e.innerHTML=`
      <style>${y}</style>
      <div class="shell login-wrap">
        <header>
          <div class="brand">Acme <span>Scoping Assistant</span></div>
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
    `;let e=this.#e.querySelector("form");e?.addEventListener("submit",t=>{t.preventDefault(),this.#f(new FormData(e))})}async#f(e){let t=this.#e.querySelector("[data-error]");t&&(t.textContent="");let n=String(e.get("subject")||"").trim();if(n.length<2){t&&(t.textContent="Enter your name so we can log who asked.");return}try{this.#t=await T(this.#o,String(e.get("password")||""),{subject:n,branch:String(e.get("branch")||"")||void 0}),b(w,this.#t),this.#c()}catch(o){t&&(t.textContent=o instanceof Error?o.message:"Sign-in failed.")}}#c(){let e=this.#t?.branch?g(this.#t.branch):"";this.#e.innerHTML=`
      <style>${y}</style>
      <div class="shell">
        <header>
          <div class="brand">Acme <span>Scoping Assistant</span></div>
          <div class="header-actions">
            ${e?`<div class="branch">${e}</div>`:""}
            <button type="button" class="new-chat" data-reset>New chat</button>
          </div>
        </header>
        <div class="messages" data-messages role="log">
          <div class="empty" data-empty>
            <p class="empty-intro">
              Central marketing covers a lot of the list, and not all of it. Ask before you brief,
              and you will know in one turn whether a job is covered, handled locally, out of scope,
              or needs a quote.
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
    `;let t=this.#e.querySelector("[data-cards]");B.forEach((r,i)=>{let a=document.createElement("button");a.type="button",a.className="card",a.innerHTML=`
        <span class="num">${String(i+1).padStart(2,"0")}</span>
        <span class="label">${g(r.label)}</span>
        <span class="hint">${g(r.message)}</span>
      `,a.addEventListener("click",()=>{this.#r(r.message)}),t?.append(a)}),this.#e.querySelector("[data-reset]")?.addEventListener("click",()=>{this.#i=null,this.#n=[],f(E),f(k),this.#c()});let n=this.#e.querySelector("form.composer"),o=this.#e.querySelector("textarea");n?.addEventListener("submit",r=>{r.preventDefault();let i=o instanceof HTMLTextAreaElement?o.value.trim():"";i&&(o instanceof HTMLTextAreaElement&&(o.value="",this.#u(o)),this.#r(i))}),o?.addEventListener("keydown",r=>{r.key==="Enter"&&!r.shiftKey&&(r.preventDefault(),n?.requestSubmit())}),o?.addEventListener("input",()=>{o instanceof HTMLTextAreaElement&&this.#u(o)})}#u(e){e.style.height="auto",e.style.height=`${Math.min(e.scrollHeight,96)}px`}#x(){this.#e.querySelector("[data-empty]")?.remove()}async#r(e,t){if(this.#l)return;this.#l=!0,this.#h(!0),this.#x(),this.#k(t?.trim()||e);let n=this.#A();this.#d=new AbortController;let o="",r=()=>{n.body.querySelector(".caret")?.remove()},i=null,a=!1,c=()=>{!a&&i&&(this.#v(n,i),a=!0),n.row.classList.remove("pending")},d=this.#n.slice();try{await H(this.#o,e,this.#i,d,this.#a?this.#t?.token??null:null,{onVerdict:l=>{i=l},onText:l=>{o+=l,c(),n.body.innerHTML=v(o);let p=document.createElement("span");p.className="caret",p.setAttribute("aria-hidden","true"),n.body.append(p),this.#s()},onDone:l=>{typeof l.text=="string"&&l.text.length>0&&(o=l.text),c(),n.body.innerHTML=v(o),this.#i=l.state,b(E,this.#i),this.#C(e,o),l.degraded&&(n.notes.textContent=(n.notes.textContent?n.notes.textContent+" ":"")+"Answered without the language model."),l.truncated&&(n.notes.textContent=(n.notes.textContent?n.notes.textContent+" ":"")+"The reply was cut short.")}},this.#d.signal,t)}catch(l){r(),c();let p=l instanceof Error?l.message:"Something went wrong.";if(p.toLowerCase().includes("unauthorised")){f(w),this.#t=null,this.#p();return}n.body.textContent=p}finally{this.#l=!1,this.#h(!1),this.#s()}}#v(e,t){if(e.status.replaceChildren(),e.banner.replaceChildren(),e.bubble.classList.toggle("handover",t.needsAHuman),t.needsAHuman){let r=document.createElement("div");r.className="handover-banner",r.textContent="Handover to a person",e.banner.append(r)}else if(t.verdict?.status&&t.verdict.service){let r=String(t.verdict.status);e.status.append(this.#g(r,$[r]??r));let i=document.createElement("div");i.className="service-title",i.textContent=String(t.verdict.service),e.status.append(i)}else t.awaitingAnswer&&e.status.append(this.#g("ask","Needs clarification"));let n=Array.isArray(t.citations)?t.citations.filter(r=>typeof r=="string"):[];n.length&&(e.citations.textContent=`Read from ${n.join("; ")}`);let o=Array.isArray(t.notes)?t.notes.filter(r=>typeof r=="string"):[];o.length&&(e.notes.textContent=o.join(" ")),t.awaitingAnswer&&t.candidates?.length?this.#y(e.candidates,t.candidates):t.actions?.length&&this.#w(e.candidates,t.actions)}#y(e,t){e.replaceChildren(),e.className="candidates",t.forEach((n,o)=>{let r=document.createElement("button");r.type="button",r.className="candidate",r.innerHTML=`
        <span class="num">${o+1}</span>
        <span class="label">${g(n.label)}</span>
      `,r.addEventListener("click",()=>{e.querySelectorAll("button").forEach(i=>{i.disabled=!0}),this.#r(n.label)}),e.append(r)})}#w(e,t){e.replaceChildren(),e.className="candidates actions",t.forEach(n=>{if(n.kind==="link"&&n.url){let a=document.createElement("a");a.className="candidate action",a.href=n.url,a.target="_blank",a.rel="noopener noreferrer",a.textContent=n.label,e.append(a);return}let o=document.createElement("button");o.type="button",o.className="candidate action";let r=typeof n.label=="string"?n.label:"Continue",i=typeof n.message=="string"&&n.message?n.message:r;o.textContent=r,o.addEventListener("click",()=>{if(n.kind==="note"){this.#E(e,n,i);return}e.querySelectorAll("button").forEach(a=>{a.disabled=!0}),this.#r(i)}),e.append(o)})}#E(e,t,n){e.replaceChildren(),e.className="note-box";let o=document.createElement("label");o.className="note-prompt",o.textContent=t.prompt||"Add some context for this request";let r=document.createElement("textarea");r.className="note-input",r.rows=3,r.placeholder=t.placeholder||"",r.maxLength=1e3,o.htmlFor=r.id=`note-${t.id}`;let i=document.createElement("button");i.type="button",i.className="candidate action note-send",i.textContent="Send it",i.disabled=!0;let a=document.createElement("button");a.type="button",a.className="candidate action note-cancel",a.textContent="Cancel";let c=document.createElement("div");c.className="note-actions",c.append(i,a),r.addEventListener("input",()=>{i.disabled=r.value.trim().length===0}),r.addEventListener("keydown",d=>{d.key==="Enter"&&!d.shiftKey&&(d.preventDefault(),i.disabled||i.click())}),i.addEventListener("click",()=>{let d=r.value.trim();d&&(i.disabled=!0,a.disabled=!0,r.disabled=!0,this.#r(n,d))}),a.addEventListener("click",()=>{e.replaceChildren(),this.#r("No")}),e.append(o,r,c),r.focus()}#k(e){let t=this.#e.querySelector("[data-messages]"),n=document.createElement("div");n.className="row user";let o=document.createElement("div");o.className="bubble",o.textContent=e,n.append(o),t?.append(n),this.#s()}#A(){let e=this.#e.querySelector("[data-messages]"),t=document.createElement("div");t.className="row assistant pending";let n=document.createElement("div");n.className="bubble";let o=document.createElement("div");o.className="live-banner",o.setAttribute("aria-live","polite");let r=document.createElement("div");r.className="bubble-inner";let i=document.createElement("div");i.className="live",i.setAttribute("aria-live","polite");let a=document.createElement("div");a.className="prose";let c=document.createElement("div"),d=document.createElement("div");d.className="citations";let l=document.createElement("div");l.className="note";let p=document.createElement("div");return p.className="waiting",p.textContent="Looking that up\u2026",p.setAttribute("aria-hidden","true"),r.append(i,a,c,d,l),n.append(o,r,p),t.append(n),e?.append(t),this.#s(),{row:t,bubble:n,banner:o,status:i,body:a,candidates:c,citations:d,notes:l}}#g(e,t){let n=document.createElement("div");return n.className=`verdict ${e}`,n.textContent=t,n}#h(e){let t=this.#e.querySelector("[data-send]"),n=this.#e.querySelector("textarea");t&&(t.disabled=e),n&&(n.disabled=e)}#s(){let e=this.#e.querySelector("[data-messages]");e&&(e.scrollTop=e.scrollHeight)}#S(){let e=m(k);return Array.isArray(e)?e.filter(t=>!!t&&(t.role==="user"||t.role==="assistant")&&typeof t.content=="string"&&t.content.trim().length>0).slice(-M):[]}#C(e,t){let n=(r,i=11e3)=>r.length<=i?r:`${r.slice(0,i-1)}\u2026`,o=[...this.#n,{role:"user",content:n(e,2e3)},{role:"assistant",content:n(t)}];this.#n=o.slice(-M),b(k,this.#n)}};customElements.get("acme-chat")||customElements.define("acme-chat",A);export{A as AcmeChat,g as escapeHtml,v as renderMarkdown};
