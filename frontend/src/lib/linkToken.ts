/**
 * The token in an emailed link's fragment (`/invite#token`): browsers never send
 * the fragment to a server, so it stays out of access logs. Once read, it is
 * taken out of the address bar and the history, and kept for this tab only, so
 * a reload, or signing in first, still has it.
 */
export function takeLinkToken(storageKey: string): string | null {
  const fromLink = window.location.hash.slice(1);
  if (fromLink) {
    try {
      sessionStorage.setItem(storageKey, fromLink);
    } catch {
      // Without storage the token lasts as long as the page.
    }
    history.replaceState(history.state, "", window.location.pathname + window.location.search);
    return fromLink;
  }
  try {
    return sessionStorage.getItem(storageKey);
  } catch {
    return null;
  }
}

/** Forgets the token once it was used. */
export function forgetLinkToken(storageKey: string) {
  try {
    sessionStorage.removeItem(storageKey);
  } catch {
    // Nothing was kept.
  }
}
