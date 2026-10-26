import { ref } from "vue";

/**
 * The API key the web app sends, kept in this browser. Without one, the app
 * works against a server with authentication off; a 401 asks for a key.
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
/** True once the server refused a request for want of a (valid) key. */
export const keyNeeded = ref(false);

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

/** Notes a refused request: an unknown or missing key opens the sign-in dialog. */
export function noteRefusal(signal: string) {
  if (signal === "api_key_required" || signal === "api_key_invalid") keyNeeded.value = true;
}
