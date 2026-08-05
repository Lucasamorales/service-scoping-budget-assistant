async function w(a,t,r={}){let n=await fetch(`${a}/api/session`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({password:t,subject:r.subject??"internal",branch:r.branch??null,country:r.country??null})});if(!n.ok){let o=await k(n);throw new Error(o||"Could not sign in.")}let e=await n.json();return{token:e.token,expiresAt:e.expiresAt,role:e.role,country:e.country,branch:e.branch}}async function S(a,t,r,n,e,o){let s={"Content-Type":"application/json"};n&&(s.Authorization=`Bearer ${n}`);let i=await fetch(`${a}/api/chat/stream`,{method:"POST",headers:s,body:JSON.stringify({message:t,state:r}),signal:o});if(!i.ok||!i.body){let c=await k(i);throw new Error(c||`Request failed (${i.status})`)}let T=i.body.getReader(),E=new TextDecoder,l="";for(;;){let{value:c,done:C}=await T.read();if(C)break;l+=E.decode(c,{stream:!0});let y=l.split(`

`);l=y.pop()??"";for(let L of y)x(L,e)}l.trim()&&x(l,e)}function x(a,t){let r="message",n="";for(let o of a.split(`
`))o.startsWith("event:")?r=o.slice(6).trim():o.startsWith("data:")&&(n+=o.slice(5).trim());if(!n)return;let e=JSON.parse(n);r==="verdict"?t.onVerdict(e):r==="text"?t.onText(String(e.text??"")):r==="done"&&t.onDone(e)}async function k(a){try{return(await a.json()).detail??""}catch{return""}}var q={"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"};function d(a){return a.replace(/[&<>"']/g,t=>q[t]??t)}function u(a){return d(a).replace(/\*\*(.+?)\*\*/g,"<strong>$1</strong>").replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g,"<em>$1</em>").replace(/_(.+?)_/g,"<em>$1</em>").replace(/\n/g,"<br>")}function m(a){try{let t=sessionStorage.getItem(a);return t?JSON.parse(t):null}catch{return null}}function p(a,t){try{sessionStorage.setItem(a,JSON.stringify(t))}catch{}}function g(a){try{sessionStorage.removeItem(a)}catch{}}var f=`
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
  content: "\u2026";
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
`;var h="acme.session",b="acme.state",H=[{label:"Merch for a launch",message:"Can we order merch for a branch opening?"},{label:"Billboard advert",message:"Can we put an advert on a billboard?"},{label:"Translate web pages",message:"Can you translate our web pages into Spanish?"},{label:"SEO audit",message:"Do we cover an SEO audit?"}],A={in_scope:"In scope",out_of_scope:"Out of scope",local:"Local",quote_required:"Quote required"},v=class extends HTMLElement{#e;#r;#o=!1;#t=null;#n=null;#s=!1;#a=null;constructor(){super(),this.#e=this.attachShadow({mode:"open"}),this.#r=(this.getAttribute("api-base")||"").replace(/\/$/,"")}connectedCallback(){this.#t=m(h),this.#n=m(b),this.#g()}disconnectedCallback(){this.#a?.abort()}async#g(){try{let t=await fetch(`${this.#r}/api/health`).then(r=>r.json());this.#o=!!t.authRequired}catch{this.#o=!1}if(this.#o&&!this.#f()){this.#c();return}this.#i()}#f(){return!!(this.#t?.token&&this.#t.expiresAt*1e3>Date.now())}#c(){this.#e.innerHTML=`
      <style>${f}</style>
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
    `;let t=this.#e.querySelector("form");t?.addEventListener("submit",r=>{r.preventDefault(),this.#h(new FormData(t))})}async#h(t){let r=this.#e.querySelector("[data-error]");r&&(r.textContent="");try{this.#t=await w(this.#r,String(t.get("password")||""),{branch:String(t.get("branch")||"")||void 0}),p(h,this.#t),this.#i()}catch(n){r&&(r.textContent=n instanceof Error?n.message:"Sign-in failed.")}}#i(){this.#e.innerHTML=`
      <style>${f}</style>
      <div class="shell">
        <header>
          <div class="brand">Acme <span>Scoping Assistant</span></div>
          <div class="meta">
            ${this.#t?.branch?d(this.#t.branch)+" \xB7 ":""}
            <button type="button" class="secondary" data-reset>New chat</button>
          </div>
        </header>
        <div class="messages" data-messages>
          <div class="empty">
            Ask whether a marketing request is covered by central marketing, handled locally,
            refused, or needs quoting. Verdicts come from the service breakdown \u2014 not from the model guessing.
          </div>
        </div>
        <div class="starters" data-starters></div>
        <form class="composer">
          <textarea name="message" rows="1" placeholder="e.g. Can we do a billboard for the new branch?" required></textarea>
          <button type="submit" data-send>Ask</button>
        </form>
      </div>
    `;let t=this.#e.querySelector("[data-starters]");for(let e of H){let o=document.createElement("button");o.type="button",o.textContent=e.label,o.dataset.message=e.message,o.addEventListener("click",()=>{this.#u(e.message)}),t?.append(o)}this.#e.querySelector("[data-reset]")?.addEventListener("click",()=>{this.#n=null,g(b),this.#i()});let r=this.#e.querySelector("form.composer"),n=this.#e.querySelector("textarea");r?.addEventListener("submit",e=>{e.preventDefault();let o=n instanceof HTMLTextAreaElement?n.value.trim():"";o&&(n instanceof HTMLTextAreaElement&&(n.value=""),this.#u(o))}),n?.addEventListener("keydown",e=>{e.key==="Enter"&&!e.shiftKey&&(e.preventDefault(),r?.requestSubmit())})}async#u(t){if(this.#s)return;this.#s=!0,this.#p(!0);let r=this.#e.querySelector("[data-messages]"),n=this.#e.querySelector("[data-starters]");n&&n.replaceChildren(),r?.querySelector(".empty")?.remove(),this.#m("user",d(t));let e=this.#b();this.#a=new AbortController;let o="";try{await S(this.#r,t,this.#n,this.#o?this.#t?.token??null:null,{onVerdict:s=>{e.badge.replaceChildren(),s.needsAHuman?e.badge.append(this.#l("handover","Handover")):s.verdict?e.badge.append(this.#l(s.verdict.status,A[s.verdict.status]??s.verdict.status)):s.awaitingAnswer&&e.badge.append(this.#l("ask","Needs clarification")),e.citations.textContent=s.citations.length?`Read from ${s.citations.join("; ")}`:"",s.notes.length&&(e.notes.textContent=s.notes.join(" "))},onText:s=>{o+=s,e.body.classList.remove("typing"),e.body.innerHTML=u(o),this.#d()},onDone:s=>{o=s.text||o,e.body.classList.remove("typing"),e.body.innerHTML=u(o),this.#n=s.state,p(b,this.#n),s.degraded&&(e.notes.textContent=(e.notes.textContent?e.notes.textContent+" ":"")+"Answered without the language model."),s.truncated&&(e.notes.textContent=(e.notes.textContent?e.notes.textContent+" ":"")+"The reply was cut short.")}},this.#a.signal)}catch(s){e.body.classList.remove("typing");let i=s instanceof Error?s.message:"Something went wrong.";if(i.toLowerCase().includes("unauthorised")){g(h),this.#t=null,this.#c();return}e.body.textContent=i}finally{this.#s=!1,this.#p(!1),this.#d()}}#m(t,r){let n=this.#e.querySelector("[data-messages]"),e=document.createElement("div");e.className=`row ${t}`;let o=document.createElement("div");return o.className="bubble",o.innerHTML=r,e.append(o),n?.append(e),this.#d(),o}#b(){let t=this.#m("assistant",""),r=document.createElement("div"),n=document.createElement("div");n.className="typing",n.textContent="Looking that up";let e=document.createElement("div");e.className="citations";let o=document.createElement("div");return o.className="note",t.replaceChildren(r,n,e,o),{badge:r,body:n,citations:e,notes:o}}#l(t,r){let n=document.createElement("div");return n.className=`verdict ${t}`,n.textContent=r,n}#p(t){let r=this.#e.querySelector("[data-send]"),n=this.#e.querySelector("textarea");r&&(r.disabled=t),n&&(n.disabled=t)}#d(){let t=this.#e.querySelector("[data-messages]");t&&(t.scrollTop=t.scrollHeight)}};customElements.get("acme-chat")||customElements.define("acme-chat",v);export{v as AcmeChat,d as escapeHtml,u as renderMarkdown};
