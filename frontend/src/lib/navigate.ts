/** Loads a page of the app afresh, so nothing loaded before signing in or out stays. */
export function reloadAt(path: string) {
  window.location.assign(path);
}
