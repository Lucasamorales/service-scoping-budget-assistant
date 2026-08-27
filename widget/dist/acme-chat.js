async function H(a,e,t){let n=await fetch(`${a}/api/session`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({password:e,subject:t.subject,branch:t.branch??null,country:t.country??null})});if(!n.ok){let r=await M(n);throw new Error(r||"Could not sign in.")}let o=await n.json();return{token:o.token,expiresAt:o.expiresAt,role:o.role,subject:o.subject??t.subject,country:o.country,branch:o.branch}}async function L(a,e,t,n,o,r,i){let s={"Content-Type":"application/json"};o&&(s.Authorization=`Bearer ${o}`);let d=await fetch(`${a}/api/chat/stream`,{method:"POST",headers:s,body:JSON.stringify({message:e,state:t,history:n}),signal:i});if(!d.ok||!d.body){let f=await M(d);throw new Error(f||`Request failed (${d.status})`)}let l=d.body.getReader(),p=new TextDecoder,c="";for(;;){let{value:f,done:z}=await l.read();if(z)break;c+=p.decode(f,{stream:!0});let T=c.split(`

`);c=T.pop()??"";for(let N of T)S(N,r)}c.trim()&&S(c,r)}function S(a,e){let t="message",n=[];for(let i of a.split(`
`))i.startsWith("event:")?t=i.slice(6).trim():i.startsWith("data:")&&n.push(i.slice(5).replace(/^ /,""));let o=n.join(`
`);if(!o)return;let r;try{r=JSON.parse(o)}catch{return}if(t==="verdict"){let i=r,s=i.verdict;e.onVerdict({verdict:s&&typeof s=="object"?{status:u(s.status),meaning:u(s.meaning),service:u(s.service)}:null,citations:C(i.citations),notes:C(i.notes),needsAHuman:!!i.needsAHuman,awaitingAnswer:!!i.awaitingAnswer,candidates:Array.isArray(i.candidates)?i.candidates:[],actions:Array.isArray(i.actions)?i.actions:[]})}else if(t==="text"){let i=u(r.text);i&&e.onText(i)}else if(t==="done"){let i=r;e.onDone({...i,text:u(i.text),source:u(i.source)||"deterministic",degraded:!!i.degraded,truncated:!!i.truncated})}}function u(a){return typeof a!="string"||a==="[object Object]"?"":a}function C(a){return Array.isArray(a)?a.map(e=>u(e)).filter(Boolean):[]}async function M(a){try{let e=await a.json();return j(e.detail)}catch{return""}}function j(a){return typeof a=="string"?a:Array.isArray(a)?a.map(t=>{if(typeof t=="string")return t;if(t&&typeof t=="object"&&"msg"in t){let n=t.msg,o=t.loc,r=Array.isArray(o)?o.join("."):"";return typeof n=="string"?r?`${r}: ${n}`:n:""}return""}).filter(Boolean).join("; ")||"Request failed validation.":a&&typeof a=="object"?"Request failed.":""}var $={"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"};function g(a){return a.replace(/[&<>"']/g,e=>$[e]??e)}function x(a){return g(typeof a=="string"?a:"").replace(/\*\*(.+?)\*\*/g,"<strong>$1</strong>").replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g,"<em>$1</em>").replace(/_(.+?)_/g,"<em>$1</em>").replace(/\n/g,"<br>")}function h(a){try{let e=sessionStorage.getItem(a);return e?JSON.parse(e):null}catch{return null}}function b(a,e){try{sessionStorage.setItem(a,JSON.stringify(e))}catch{}}function m(a){try{sessionStorage.removeItem(a)}catch{}}function D(a){try{let e=localStorage.getItem(a);return e==="navy"||e==="light"?e:null}catch{return null}}function v(a,e){try{localStorage.setItem(a,e)}catch{}}function q(a){let e=D(a);if(e)return e;try{if(window.matchMedia("(prefers-color-scheme: light)").matches)return"light"}catch{}return"navy"}var y=`
:host {
  --canvas: #101A33;
  --panel: #232F55;
  --surface: #2E3D6E;
  --surface-alt: #25355F;
  --input-bg: #1B2547;
  --accent: #6BB0E0;
  --red: #EE2C2C;
  --user-bg: #3B6BA5;
  --text: #FFFFFF;
  --body: rgba(255, 255, 255, 0.9);
  --text-soft: rgba(255, 255, 255, 0.62);
  --text-faint: rgba(255, 255, 255, 0.4);
  --line: rgba(255, 255, 255, 0.14);
  --hair: rgba(255, 255, 255, 0.1);
  --toggle-line: rgba(255, 255, 255, 0.22);
  --header-bg: transparent;
  --header-border: rgba(255, 255, 255, 0.1);
  --header-text: #FFFFFF;
  --handover-bubble: #33223A;
  --handover-border: rgba(238, 44, 44, 0.45);
  --note: #E08A6A;
  --login-input-bg: rgba(255, 255, 255, 0.06);

  --pill-in-fg: #6ED39B;
  --pill-in-bg: rgba(110, 211, 155, 0.14);
  --pill-in-bd: rgba(110, 211, 155, 0.55);
  --pill-quote-fg: #9CCCEC;
  --pill-quote-bg: rgba(107, 176, 224, 0.14);
  --pill-quote-bd: rgba(107, 176, 224, 0.55);
  --pill-local-fg: #E8B23C;
  --pill-local-bg: rgba(232, 178, 60, 0.12);
  --pill-local-bd: rgba(232, 178, 60, 0.5);
  --pill-out-fg: #C0A99A;
  --pill-out-bg: rgba(192, 169, 154, 0.12);
  --pill-out-bd: rgba(192, 169, 154, 0.45);
  --pill-ask-fg: #F0B27A;
  --pill-ask-bg: rgba(240, 178, 122, 0.12);
  --pill-ask-bd: rgba(240, 178, 122, 0.5);

  --font-ui: "Archivo", "Segoe UI", sans-serif;
  --font-display: "Caveat Brush", "Segoe Print", cursive;

  display: block;
  color: var(--text);
  font-family: var(--font-ui);
  font-size: 15px;
  line-height: 1.45;
}

.shell[data-theme="light"],
:host([data-theme="light"]) .shell {
  --canvas: #E4EBF2;
  --panel: #F4F7FA;
  --surface: #FFFFFF;
  --surface-alt: #F0F4F8;
  --input-bg: #FFFFFF;
  --accent: #3B6BA5;
  --user-bg: #232F55;
  --text: #14213B;
  --body: #2C3D50;
  --text-soft: #5A6E85;
  --text-faint: #8A9BAD;
  --line: #D7E0EA;
  --hair: #E8EEF4;
  --toggle-line: rgba(255, 255, 255, 0.28);
  --header-bg: #232F55;
  --header-border: transparent;
  --header-text: #FFFFFF;
  --handover-bubble: #FFFFFF;
  --handover-border: #F2C2C2;
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

.theme-toggle {
  display: flex;
  gap: 3px;
  padding: 3px;
  border: 1px solid var(--toggle-line);
  border-radius: 999px;
  flex-shrink: 0;
}

.theme-toggle button {
  appearance: none;
  border: 0;
  background: transparent;
  color: rgba(255, 255, 255, 0.65);
  font: inherit;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
  padding: 6px 12px;
  border-radius: 999px;
  cursor: pointer;
}

.theme-toggle button[aria-pressed="true"] {
  background: #6BB0E0;
  color: #14213B;
}

.theme-toggle button:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
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
`;var w="acme.session",E="acme.state",A="acme.history",k="acme.theme",B=12,I=[{label:"Merch for a launch",message:"Can we order merch for a branch opening?"},{label:"Billboard advert",message:"Can we put an advert on a billboard?"},{label:"Translate web pages",message:"Can you translate our web pages into Spanish?"}],O={in_scope:"In scope",out_of_scope:"Out of scope",local:"Local",quote_required:"Quote required"},F=class extends HTMLElement{#e;#o;#a=!1;#n=null;#i=null;#r=[];#t="navy";#c=!1;#p=null;constructor(){super(),this.#e=this.attachShadow({mode:"open"}),this.#o=(this.getAttribute("api-base")||"").replace(/\/$/,"")}connectedCallback(){this.#t=q(k),this.#n=h(w),this.#i=h(E),this.#r=this.#C(),this.#v()}disconnectedCallback(){this.#p?.abort()}async#v(){try{let e=await fetch(`${this.#o}/api/health`).then(t=>t.json());this.#a=!!e.authRequired}catch{this.#a=!1}if(this.#a&&!this.#y()){this.#b();return}this.#u()}#y(){return!!(this.#n?.token&&this.#n.expiresAt*1e3>Date.now())}#s(e){e?.setAttribute("data-theme",this.#t),this.setAttribute("data-theme",this.#t);let t=this.#e.querySelector("[data-theme-navy]"),n=this.#e.querySelector("[data-theme-light]");t&&t.setAttribute("aria-pressed",this.#t==="navy"?"true":"false"),n&&n.setAttribute("aria-pressed",this.#t==="light"?"true":"false")}#g(e){this.#e.querySelector("[data-theme-navy]")?.addEventListener("click",()=>{this.#t="navy",v(k,this.#t),this.#s(e)}),this.#e.querySelector("[data-theme-light]")?.addEventListener("click",()=>{this.#t="light",v(k,this.#t),this.#s(e)})}#h(){return`
      <div class="theme-toggle" role="group" aria-label="Colour theme">
        <button type="button" data-theme-navy aria-pressed="${this.#t==="navy"}">Navy</button>
        <button type="button" data-theme-light aria-pressed="${this.#t==="light"}">Light</button>
      </div>
    `}#b(){this.#e.innerHTML=`
      <style>${y}</style>
      <div class="shell login-wrap" data-theme="${this.#t}">
        <header>
          <div class="brand">Acme <span>Scoping Assistant</span></div>
          <div class="header-actions">${this.#h()}</div>
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
    `;let e=this.#e.querySelector(".shell");this.#s(e),this.#g(e);let t=this.#e.querySelector("form");t?.addEventListener("submit",n=>{n.preventDefault(),this.#w(new FormData(t))})}async#w(e){let t=this.#e.querySelector("[data-error]");t&&(t.textContent="");let n=String(e.get("subject")||"").trim();if(n.length<2){t&&(t.textContent="Enter your name so we can log who asked.");return}try{this.#n=await H(this.#o,String(e.get("password")||""),{subject:n,branch:String(e.get("branch")||"")||void 0}),b(w,this.#n),this.#u()}catch(o){t&&(t.textContent=o instanceof Error?o.message:"Sign-in failed.")}}#u(){let e=this.#n?.branch?g(this.#n.branch):"";this.#e.innerHTML=`
      <style>${y}</style>
      <div class="shell" data-theme="${this.#t}">
        <header>
          <div class="brand">Acme <span>Scoping Assistant</span></div>
          <div class="header-actions">
            ${e?`<div class="branch">${e}</div>`:""}
            ${this.#h()}
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
    `;let t=this.#e.querySelector(".shell");this.#s(t),this.#g(t);let n=this.#e.querySelector("[data-cards]");I.forEach((i,s)=>{let d=document.createElement("button");d.type="button",d.className="card",d.innerHTML=`
        <span class="num">${String(s+1).padStart(2,"0")}</span>
        <span class="label">${g(i.label)}</span>
        <span class="hint">${g(i.message)}</span>
      `,d.addEventListener("click",()=>{this.#l(i.message)}),n?.append(d)}),this.#e.querySelector("[data-reset]")?.addEventListener("click",()=>{this.#i=null,this.#r=[],m(E),m(A),this.#u()});let o=this.#e.querySelector("form.composer"),r=this.#e.querySelector("textarea");o?.addEventListener("submit",i=>{i.preventDefault();let s=r instanceof HTMLTextAreaElement?r.value.trim():"";s&&(r instanceof HTMLTextAreaElement&&(r.value="",this.#m(r)),this.#l(s))}),r?.addEventListener("keydown",i=>{i.key==="Enter"&&!i.shiftKey&&(i.preventDefault(),o?.requestSubmit())}),r?.addEventListener("input",()=>{r instanceof HTMLTextAreaElement&&this.#m(r)})}#m(e){e.style.height="auto",e.style.height=`${Math.min(e.scrollHeight,96)}px`}#E(){this.#e.querySelector("[data-empty]")?.remove()}async#l(e){if(this.#c)return;this.#c=!0,this.#x(!0),this.#E(),this.#T(e);let t=this.#S();this.#p=new AbortController;let n="",o=null,r=null,i=!1,s=()=>{!i&&r&&(this.#A(t,r),i=!0),t.row.classList.remove("pending")},d=this.#r.slice();try{await L(this.#o,e,this.#i,d,this.#a?this.#n?.token??null:null,{onVerdict:l=>{r=l},onText:l=>{n+=l,s(),o||(o=document.createElement("span"),o.className="caret",o.setAttribute("aria-hidden","true")),t.body.innerHTML=x(n),t.body.append(o),this.#d()},onDone:l=>{typeof l.text=="string"&&l.text.length>0&&(n=l.text),s(),o?.remove(),o=null,t.body.innerHTML=x(n),this.#i=l.state,b(E,this.#i),this.#H(e,n),l.degraded&&(t.notes.textContent=(t.notes.textContent?t.notes.textContent+" ":"")+"Answered without the language model."),l.truncated&&(t.notes.textContent=(t.notes.textContent?t.notes.textContent+" ":"")+"The reply was cut short.")}},this.#p.signal)}catch(l){o?.remove(),s();let p=l instanceof Error?l.message:"Something went wrong.";if(p.toLowerCase().includes("unauthorised")){m(w),this.#n=null,this.#b();return}t.body.textContent=p}finally{this.#c=!1,this.#x(!1),this.#d()}}#A(e,t){if(e.status.replaceChildren(),e.banner.replaceChildren(),e.bubble.classList.toggle("handover",t.needsAHuman),t.needsAHuman){let r=document.createElement("div");r.className="handover-banner",r.textContent="Handover to a person",e.banner.append(r)}else if(t.verdict?.status&&t.verdict.service){let r=String(t.verdict.status);e.status.append(this.#f(r,O[r]??r));let i=document.createElement("div");i.className="service-title",i.textContent=String(t.verdict.service),e.status.append(i)}else t.awaitingAnswer&&e.status.append(this.#f("ask","Needs clarification"));let n=Array.isArray(t.citations)?t.citations.filter(r=>typeof r=="string"):[];n.length&&(e.citations.textContent=`Read from ${n.join("; ")}`);let o=Array.isArray(t.notes)?t.notes.filter(r=>typeof r=="string"):[];o.length&&(e.notes.textContent=o.join(" ")),t.awaitingAnswer&&t.candidates?.length?this.#k(e.candidates,t.candidates):t.actions?.length&&this.#F(e.candidates,t.actions)}#k(e,t){e.replaceChildren(),e.className="candidates",t.forEach((n,o)=>{let r=document.createElement("button");r.type="button",r.className="candidate",r.innerHTML=`
        <span class="num">${o+1}</span>
        <span class="label">${g(n.label)}</span>
      `,r.addEventListener("click",()=>{e.querySelectorAll("button").forEach(i=>{i.disabled=!0}),this.#l(n.label)}),e.append(r)})}#F(e,t){e.replaceChildren(),e.className="candidates actions",t.forEach(n=>{if(n.kind==="link"&&n.url){let s=document.createElement("a");s.className="candidate action",s.href=n.url,s.target="_blank",s.rel="noopener noreferrer",s.textContent=n.label,e.append(s);return}let o=document.createElement("button");o.type="button",o.className="candidate action";let r=typeof n.label=="string"?n.label:"Continue",i=typeof n.message=="string"&&n.message?n.message:r;o.textContent=r,o.addEventListener("click",()=>{e.querySelectorAll("button").forEach(s=>{s.disabled=!0}),this.#l(i)}),e.append(o)})}#T(e){let t=this.#e.querySelector("[data-messages]"),n=document.createElement("div");n.className="row user";let o=document.createElement("div");o.className="bubble",o.textContent=e,n.append(o),t?.append(n),this.#d()}#S(){let e=this.#e.querySelector("[data-messages]"),t=document.createElement("div");t.className="row assistant pending";let n=document.createElement("div");n.className="bubble";let o=document.createElement("div");o.className="live-banner",o.setAttribute("aria-live","polite");let r=document.createElement("div");r.className="bubble-inner";let i=document.createElement("div");i.className="live",i.setAttribute("aria-live","polite");let s=document.createElement("div");s.className="prose";let d=document.createElement("div"),l=document.createElement("div");l.className="citations";let p=document.createElement("div");p.className="note";let c=document.createElement("div");return c.className="waiting",c.textContent="Looking that up\u2026",c.setAttribute("aria-hidden","true"),r.append(i,s,d,l,p),n.append(o,r,c),t.append(n),e?.append(t),this.#d(),{row:t,bubble:n,banner:o,status:i,body:s,candidates:d,citations:l,notes:p}}#f(e,t){let n=document.createElement("div");return n.className=`verdict ${e}`,n.textContent=t,n}#x(e){let t=this.#e.querySelector("[data-send]"),n=this.#e.querySelector("textarea");t&&(t.disabled=e),n&&(n.disabled=e)}#d(){let e=this.#e.querySelector("[data-messages]");e&&(e.scrollTop=e.scrollHeight)}#C(){let e=h(A);return Array.isArray(e)?e.filter(t=>!!t&&(t.role==="user"||t.role==="assistant")&&typeof t.content=="string"&&t.content.trim().length>0).slice(-B):[]}#H(e,t){let n=(r,i=11e3)=>r.length<=i?r:`${r.slice(0,i-1)}\u2026`,o=[...this.#r,{role:"user",content:n(e,2e3)},{role:"assistant",content:n(t)}];this.#r=o.slice(-B),b(A,this.#r)}};customElements.get("acme-chat")||customElements.define("acme-chat",F);export{F as AcmeChat,g as escapeHtml,x as renderMarkdown};
