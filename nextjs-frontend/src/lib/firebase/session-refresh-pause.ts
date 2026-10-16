/**
 * Lets a flow that deliberately revokes and re-creates the session (the password change, KAN-208) keep the
 * background session refresh (`useSessionRefresh`) from racing it. That hook reacts to every ID token change, and
 * the change's own re-authentication and re-sign-in are token changes: refreshing in parallel would see the
 * freshly revoked cookie, drop it and sign the user out, or mint a second session.
 */
let paused = false;

export function setSessionRefreshPaused(value: boolean): void {
  paused = value;
}

export function isSessionRefreshPaused(): boolean {
  return paused;
}
