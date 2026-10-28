/** Loads a page of the app afresh, so nothing loaded before signing in or out stays. */
export function reloadAt(path: string) {
  window.location.assign(path);
}

/** Leaves the app for another site, such as a service's sign-in page. */
export function goTo(url: string) {
  window.location.assign(url);
}
