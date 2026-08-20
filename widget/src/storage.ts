/** Best-effort storage — Safari private mode can throw. */

export function readJson<T>(key: string): T | null {
  try {
    const raw = sessionStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

export function writeJson(key: string, value: unknown): void {
  try {
    sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Persistence is convenient, never load-bearing.
  }
}

export function removeKey(key: string): void {
  try {
    sessionStorage.removeItem(key);
  } catch {
    // ignore
  }
}

export type Theme = "navy" | "light";

export function readTheme(key: string): Theme | null {
  try {
    const raw = localStorage.getItem(key);
    if (raw === "navy" || raw === "light") return raw;
    return null;
  } catch {
    return null;
  }
}

export function writeTheme(key: string, theme: Theme): void {
  try {
    localStorage.setItem(key, theme);
  } catch {
    // ignore
  }
}

export function resolveInitialTheme(key: string): Theme {
  const stored = readTheme(key);
  if (stored) return stored;
  try {
    if (window.matchMedia("(prefers-color-scheme: light)").matches) return "light";
  } catch {
    // ignore
  }
  return "navy";
}
