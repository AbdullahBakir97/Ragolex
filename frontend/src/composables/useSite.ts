import { ref } from "vue";

import { api } from "@/api/client";
import type { Site } from "@/api/types";

// What the domain the app is opened on serves: a workspace's own domain, or
// the server's, where people may sign up. Asked once per page load.
const site = ref<Site | null>(null);
let loading: Promise<Site | null> | null = null;

function load(): Promise<Site | null> {
  loading ??= api
    .site()
    .then((found) => (site.value = found))
    .catch(() => null);
  return loading;
}

/** Asks again on the next load (after a domain changed, and between tests). */
function forget() {
  loading = null;
  site.value = null;
}

export function useSite() {
  return { site, load, forget };
}
