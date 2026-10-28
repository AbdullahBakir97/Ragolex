import { ref } from "vue";

/**
 * How the web app proves who it is. People sign in with an email and a
 * password: the server then sets an HttpOnly session cookie, which scripts
 * never see and the browser sends by itself. An API key, kept in this
 * browser, works too and wins over the cookie. Without either, the app works
 * against a server with authentication off; a 401 sends it to the sign-in page.
 */
const STORAGE_KEY = "ragolex.api-key";

function stored(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export const apiKey = ref<string | null>(stored());
/** True once the server refused a request for want of a key or a session. */
export const signInNeeded = ref(false);
/** Why signing in is needed again, when the reason is worth saying. */
export const signInReason = ref<string | null>(null);

export function setApiKey(key: string | null) {
  apiKey.value = key;
  try {
    if (key) localStorage.setItem(STORAGE_KEY, key);
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Private windows may refuse storage; the key then lasts until the page is closed.
  }
}

export function authHeaders(): Record<string, string> {
  return apiKey.value ? { Authorization: `Bearer ${apiKey.value}` } : {};
}

const SIGN_IN_SIGNALS = new Set(["api_key_required", "api_key_invalid", "session_required"]);

/** Notes a refused request: no (valid) key or session sends the app to sign in. */
export function noteRefusal(signal: string) {
  if (!SIGN_IN_SIGNALS.has(signal)) return;
  if (apiKey.value) {
    // A key that was refused is no use any more.
    signInReason.value = "The saved API key no longer works.";
    setApiKey(null);
  } else if (signal === "session_required") {
    signInReason.value = "Your session has ended. Sign in again.";
  }
  signInNeeded.value = true;
}

/**
 * Where to go after signing in: a page of this app, never another site
 * (`next` comes from the address bar, which anyone can link to).
 */
export function safeNext(next: unknown): string {
  if (typeof next !== "string" || !next.startsWith("/")) return "/";
  // Resolved as the browser will: it drops tabs and newlines and reads "\\" as "/",
  // so "/\t/evil.example" is another site even though it starts with one "/".
  try {
    const url = new URL(next, window.location.origin);
    return url.origin === window.location.origin ? url.pathname + url.search + url.hash : "/";
  } catch {
    return "/";
  }
}
