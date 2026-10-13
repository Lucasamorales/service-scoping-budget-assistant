# widget

The chat widget: a custom element, `<acme-chat>`, written in TypeScript and bundled with esbuild
into one file with no runtime dependencies.

| Path | What it is |
|---|---|
| `src/chat.ts` | The custom element: the conversation, the service list, the sign-in gate |
| `src/api.ts` | The widget's whole view of the service: session, catalogue, and decoding the reply stream |
| `src/markdown.ts` | Escapes model text and applies a small safe subset of markdown |
| `src/storage.ts` | Keeps the conversation across a reload, and carries on when the browser refuses |
| `src/styles.ts` | The widget's CSS, inlined so the bundle stays one file |
| `dist/acme-chat.js` | The built bundle. Committed, because the image copies it; CI rebuilds it and fails if it is stale |
| `assets/` | Fonts and the placeholder logo |
| `index.html`, `embed-webflow.html` | A local test page, and the snippet for embedding the widget in a site |

```bash
npm ci
```

```bash
npm run build
```

```bash
npm test
```

The tests run the TypeScript sources directly with Node 22's own test runner, so there is no
test framework to install. They cover `api.ts`, `markdown.ts` and `storage.ts`; the element in
`chat.ts` is exercised by hand through `index.html`.
