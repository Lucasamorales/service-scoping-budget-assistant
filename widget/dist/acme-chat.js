async function C(a,t,e){let n=await fetch(`${a}/api/session`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({password:t,subject:e.subject,branch:e.branch??null,country:e.country??null})});if(!n.ok){let r=await H(n);throw new Error(r||"Could not sign in.")}let i=await n.json();return{token:i.token,expiresAt:i.expiresAt,role:i.role,subject:i.subject??e.subject,country:i.country,branch:i.branch}}async function T(a,t,e,n,i,r,o){let s={"Content-Type":"application/json"};i&&(s.Authorization=`Bearer ${i}`);let c=await fetch(`${a}/api/chat/stream`,{method:"POST",headers:s,body:JSON.stringify({message:t,state:e,history:n}),signal:o});if(!c.ok||!c.body){let f=await H(c);throw new Error(f||`Request failed (${c.status})`)}let l=c.body.getReader(),d=new TextDecoder,p="";for(;;){let{value:f,done:M}=await l.read();if(M)break;p+=d.decode(f,{stream:!0});let A=p.split(`

`);p=A.pop()??"";for(let q of A)F(q,r)}p.trim()&&F(p,r)}function F(a,t){let e="message",n=[];for(let o of a.split(`
`))o.startsWith("event:")?e=o.slice(6).trim():o.startsWith("data:")&&n.push(o.slice(5).replace(/^ /,""));let i=n.join(`
`);if(!i)return;let r;try{r=JSON.parse(i)}catch{return}if(e==="verdict"){let o=r,s=o.verdict;t.onVerdict({verdict:s&&typeof s=="object"?{status:u(s.status),meaning:u(s.meaning),service:u(s.service)}:null,citations:S(o.citations),notes:S(o.notes),needsAHuman:!!o.needsAHuman,awaitingAnswer:!!o.awaitingAnswer,candidates:Array.isArray(o.candidates)?o.candidates:[],actions:Array.isArray(o.actions)?o.actions:[]})}else if(e==="text"){let o=u(r.text);o&&t.onText(o)}else if(e==="done"){let o=r;t.onDone({...o,text:u(o.text),source:u(o.source)||"deterministic",degraded:!!o.degraded,truncated:!!o.truncated})}}function u(a){return typeof a!="string"||a==="[object Object]"?"":a}function S(a){return Array.isArray(a)?a.map(t=>u(t)).filter(Boolean):[]}async function H(a){try{let t=await a.json();return N(t.detail)}catch{return""}}function N(a){return typeof a=="string"?a:Array.isArray(a)?a.map(e=>{if(typeof e=="string")return e;if(e&&typeof e=="object"&&"msg"in e){let n=e.msg,i=e.loc,r=Array.isArray(i)?i.join("."):"";return typeof n=="string"?r?`${r}: ${n}`:n:""}return""}).filter(Boolean).join("; ")||"Request failed validation.":a&&typeof a=="object"?"Request failed.":""}var j={"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"};function g(a){return a.replace(/[&<>"']/g,t=>j[t]??t)}function x(a){return g(typeof a=="string"?a:"").replace(/\*\*(.+?)\*\*/g,"<strong>$1</strong>").replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g,"<em>$1</em>").replace(/_(.+?)_/g,"<em>$1</em>").replace(/\n/g,"<br>")}function h(a){try{let t=sessionStorage.getItem(a);return t?JSON.parse(t):null}catch{return null}}function m(a,t){try{sessionStorage.setItem(a,JSON.stringify(t))}catch{}}function b(a){try{sessionStorage.removeItem(a)}catch{}}var v=`
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
`;var y="acme.session",w="acme.state",E="acme.history",L=12,z=[{label:"Merch for a launch",message:"Can we order merch for a branch opening?"},{label:"Billboard advert",message:"Can we put an advert on a billboard?"},{label:"Translate web pages",message:"Can you translate our web pages into Spanish?"}],B={in_scope:"In scope",out_of_scope:"Out of scope",local:"Local",quote_required:"Quote required"},k=class extends HTMLElement{#e;#i;#o=!1;#t=null;#r=null;#n=[];#l=!1;#d=null;constructor(){super(),this.#e=this.attachShadow({mode:"open"}),this.#i=(this.getAttribute("api-base")||"").replace(/\/$/,"")}connectedCallback(){this.#t=h(y),this.#r=h(w),this.#n=this.#A(),this.#m()}disconnectedCallback(){this.#d?.abort()}async#m(){try{let t=await fetch(`${this.#i}/api/health`).then(e=>e.json());this.#o=!!t.authRequired}catch{this.#o=!1}if(this.#o&&!this.#b()){this.#p();return}this.#c()}#b(){return!!(this.#t?.token&&this.#t.expiresAt*1e3>Date.now())}#p(){this.#e.innerHTML=`
      <style>${v}</style>
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
    `;let t=this.#e.querySelector("form");t?.addEventListener("submit",e=>{e.preventDefault(),this.#f(new FormData(t))})}async#f(t){let e=this.#e.querySelector("[data-error]");e&&(e.textContent="");let n=String(t.get("subject")||"").trim();if(n.length<2){e&&(e.textContent="Enter your name so we can log who asked.");return}try{this.#t=await C(this.#i,String(t.get("password")||""),{subject:n,branch:String(t.get("branch")||"")||void 0}),m(y,this.#t),this.#c()}catch(i){e&&(e.textContent=i instanceof Error?i.message:"Sign-in failed.")}}#c(){let t=this.#t?.branch?g(this.#t.branch):"";this.#e.innerHTML=`
      <style>${v}</style>
      <div class="shell">
        <header>
          <div class="brand">Acme <span>Scoping Assistant</span></div>
          <div class="header-actions">
            ${t?`<div class="branch">${t}</div>`:""}
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
    `;let e=this.#e.querySelector("[data-cards]");z.forEach((r,o)=>{let s=document.createElement("button");s.type="button",s.className="card",s.innerHTML=`
        <span class="num">${String(o+1).padStart(2,"0")}</span>
        <span class="label">${g(r.label)}</span>
        <span class="hint">${g(r.message)}</span>
      `,s.addEventListener("click",()=>{this.#a(r.message)}),e?.append(s)}),this.#e.querySelector("[data-reset]")?.addEventListener("click",()=>{this.#r=null,this.#n=[],b(w),b(E),this.#c()});let n=this.#e.querySelector("form.composer"),i=this.#e.querySelector("textarea");n?.addEventListener("submit",r=>{r.preventDefault();let o=i instanceof HTMLTextAreaElement?i.value.trim():"";o&&(i instanceof HTMLTextAreaElement&&(i.value="",this.#u(i)),this.#a(o))}),i?.addEventListener("keydown",r=>{r.key==="Enter"&&!r.shiftKey&&(r.preventDefault(),n?.requestSubmit())}),i?.addEventListener("input",()=>{i instanceof HTMLTextAreaElement&&this.#u(i)})}#u(t){t.style.height="auto",t.style.height=`${Math.min(t.scrollHeight,96)}px`}#x(){this.#e.querySelector("[data-empty]")?.remove()}async#a(t){if(this.#l)return;this.#l=!0,this.#h(!0),this.#x(),this.#E(t);let e=this.#k();this.#d=new AbortController;let n="",i=()=>{e.body.querySelector(".caret")?.remove()},r=null,o=!1,s=()=>{!o&&r&&(this.#v(e,r),o=!0),e.row.classList.remove("pending")},c=this.#n.slice();try{await T(this.#i,t,this.#r,c,this.#o?this.#t?.token??null:null,{onVerdict:l=>{r=l},onText:l=>{n+=l,s(),e.body.innerHTML=x(n);let d=document.createElement("span");d.className="caret",d.setAttribute("aria-hidden","true"),e.body.append(d),this.#s()},onDone:l=>{typeof l.text=="string"&&l.text.length>0&&(n=l.text),s(),e.body.innerHTML=x(n),this.#r=l.state,m(w,this.#r),this.#F(t,n),l.degraded&&(e.notes.textContent=(e.notes.textContent?e.notes.textContent+" ":"")+"Answered without the language model."),l.truncated&&(e.notes.textContent=(e.notes.textContent?e.notes.textContent+" ":"")+"The reply was cut short.")}},this.#d.signal)}catch(l){i(),s();let d=l instanceof Error?l.message:"Something went wrong.";if(d.toLowerCase().includes("unauthorised")){b(y),this.#t=null,this.#p();return}e.body.textContent=d}finally{this.#l=!1,this.#h(!1),this.#s()}}#v(t,e){if(t.status.replaceChildren(),t.banner.replaceChildren(),t.bubble.classList.toggle("handover",e.needsAHuman),e.needsAHuman){let r=document.createElement("div");r.className="handover-banner",r.textContent="Handover to a person",t.banner.append(r)}else if(e.verdict?.status&&e.verdict.service){let r=String(e.verdict.status);t.status.append(this.#g(r,B[r]??r));let o=document.createElement("div");o.className="service-title",o.textContent=String(e.verdict.service),t.status.append(o)}else e.awaitingAnswer&&t.status.append(this.#g("ask","Needs clarification"));let n=Array.isArray(e.citations)?e.citations.filter(r=>typeof r=="string"):[];n.length&&(t.citations.textContent=`Read from ${n.join("; ")}`);let i=Array.isArray(e.notes)?e.notes.filter(r=>typeof r=="string"):[];i.length&&(t.notes.textContent=i.join(" ")),e.awaitingAnswer&&e.candidates?.length?this.#y(t.candidates,e.candidates):e.actions?.length&&this.#w(t.candidates,e.actions)}#y(t,e){t.replaceChildren(),t.className="candidates",e.forEach((n,i)=>{let r=document.createElement("button");r.type="button",r.className="candidate",r.innerHTML=`
        <span class="num">${i+1}</span>
        <span class="label">${g(n.label)}</span>
      `,r.addEventListener("click",()=>{t.querySelectorAll("button").forEach(o=>{o.disabled=!0}),this.#a(n.label)}),t.append(r)})}#w(t,e){t.replaceChildren(),t.className="candidates actions",e.forEach(n=>{if(n.kind==="link"&&n.url){let s=document.createElement("a");s.className="candidate action",s.href=n.url,s.target="_blank",s.rel="noopener noreferrer",s.textContent=n.label,t.append(s);return}let i=document.createElement("button");i.type="button",i.className="candidate action";let r=typeof n.label=="string"?n.label:"Continue",o=typeof n.message=="string"&&n.message?n.message:r;i.textContent=r,i.addEventListener("click",()=>{t.querySelectorAll("button").forEach(s=>{s.disabled=!0}),this.#a(o)}),t.append(i)})}#E(t){let e=this.#e.querySelector("[data-messages]"),n=document.createElement("div");n.className="row user";let i=document.createElement("div");i.className="bubble",i.textContent=t,n.append(i),e?.append(n),this.#s()}#k(){let t=this.#e.querySelector("[data-messages]"),e=document.createElement("div");e.className="row assistant pending";let n=document.createElement("div");n.className="bubble";let i=document.createElement("div");i.className="live-banner",i.setAttribute("aria-live","polite");let r=document.createElement("div");r.className="bubble-inner";let o=document.createElement("div");o.className="live",o.setAttribute("aria-live","polite");let s=document.createElement("div");s.className="prose";let c=document.createElement("div"),l=document.createElement("div");l.className="citations";let d=document.createElement("div");d.className="note";let p=document.createElement("div");return p.className="waiting",p.textContent="Looking that up\u2026",p.setAttribute("aria-hidden","true"),r.append(o,s,c,l,d),n.append(i,r,p),e.append(n),t?.append(e),this.#s(),{row:e,bubble:n,banner:i,status:o,body:s,candidates:c,citations:l,notes:d}}#g(t,e){let n=document.createElement("div");return n.className=`verdict ${t}`,n.textContent=e,n}#h(t){let e=this.#e.querySelector("[data-send]"),n=this.#e.querySelector("textarea");e&&(e.disabled=t),n&&(n.disabled=t)}#s(){let t=this.#e.querySelector("[data-messages]");t&&(t.scrollTop=t.scrollHeight)}#A(){let t=h(E);return Array.isArray(t)?t.filter(e=>!!e&&(e.role==="user"||e.role==="assistant")&&typeof e.content=="string"&&e.content.trim().length>0).slice(-L):[]}#F(t,e){let n=(r,o=11e3)=>r.length<=o?r:`${r.slice(0,o-1)}\u2026`,i=[...this.#n,{role:"user",content:n(t,2e3)},{role:"assistant",content:n(e)}];this.#n=i.slice(-L),m(E,this.#n)}};customElements.get("acme-chat")||customElements.define("acme-chat",k);export{k as AcmeChat,g as escapeHtml,x as renderMarkdown};
