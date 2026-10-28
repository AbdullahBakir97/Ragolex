import { ref } from "vue";

import { setApiKey } from "@/api/auth";
import { api } from "@/api/client";
import type { Session } from "@/api/types";
import { reloadAt } from "@/lib/navigate";

// The signed-in user and their workspaces, shared by the whole app. Null when
// the app uses an API key, authentication is off, or nobody signed in.
const session = ref<Session | null>(null);
const loaded = ref(false);

async function load(): Promise<Session | null> {
  try {
    session.value = await api.session();
  } catch {
    session.value = null;
  } finally {
    loaded.value = true;
  }
  return session.value;
}

/** Ends the session (or forgets the API key) and starts again at the sign-in page. */
async function signOut() {
  await api.signOut().catch(() => undefined);
  setApiKey(null);
  session.value = null;
  reloadAt("/signin");
}

/** Works in another of the user's workspaces; the page starts again in it. */
async function switchWorkspace(name: string) {
  session.value = await api.switchWorkspace(name);
  reloadAt("/");
}

export function useSession() {
  return { session, loaded, load, signOut, switchWorkspace };
}
