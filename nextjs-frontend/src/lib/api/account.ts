import 'server-only';

import { callBackend } from './server';
import {
  createSession,
  deleteAccount,
  deleteSession,
  disable,
  readHistory,
  readProfile,
  readSession,
  readSettings,
  refreshSession,
  updateAvatar,
  updateProfile,
  updateSettings,
  type HistoryEntry,
  type ProfileData,
  type ProfileRequest,
  type SettingsData,
  type SettingsRequest,
} from './generated';

/**
 * Server-only account calls for the auth and profile server actions (KAN-41). Server actions import
 * these instead of the generated SDK, which ESLint restricts to `src/lib/api/**` (ADR-008).
 */

/** Exchanges a fresh Firebase ID token for a session cookie; the backend syncs the user and records the login. */
export function createBackendSession(idToken: string, userAgent: string | null) {
  return callBackend((client) =>
    createSession({
      client,
      body: { id_token: idToken },
      ...(userAgent ? { headers: { 'User-Agent': userAgent.slice(0, 512) } } : {}),
    })
  );
}

/**
 * Mints a new session cookie from a fresh ID token for the caller's CURRENT session (KAN-179). The backend
 * requires the same uid, records no login history and rejects an ID token too old to mint a cookie.
 */
export function refreshBackendSession(idToken: string) {
  return callBackend((client) => refreshSession({ client, body: { id_token: idToken } }));
}

export function revokeBackendSession() {
  return callBackend((client) => deleteSession({ client }));
}

/**
 * Deletes the caller's account (KAN-180). The backend requires a Firebase ID token minted in the last five
 * minutes for the same uid, so the browser re-authenticates first; the token is only forwarded, never stored.
 */
export function removeBackendAccount(idToken: string) {
  return callBackend((client) => deleteAccount({ client, body: { id_token: idToken } }));
}

/** Turns two-factor authentication off; needs the fresh ID token plus a current authenticator code. */
export function disableBackendTotp(idToken: string, code: string) {
  return callBackend((client) => disable({ client, body: { id_token: idToken, token: code } }));
}

export function fetchIdentity() {
  return callBackend((client) => readSession({ client }));
}

export function fetchProfile() {
  return callBackend((client) => readProfile({ client }));
}

export function patchProfile(body: ProfileRequest) {
  return callBackend((client) => updateProfile({ client, body }));
}

export function patchAvatar(avatarUrl: string | null) {
  return callBackend((client) => updateAvatar({ client, body: { avatar_url: avatarUrl } }));
}

export function fetchSettings() {
  return callBackend((client) => readSettings({ client }));
}

export function patchSettings(body: SettingsRequest) {
  return callBackend((client) => updateSettings({ client, body }));
}

export function fetchLoginHistory(limit: number, offset: number) {
  return callBackend((client) => readHistory({ client, query: { limit, offset } }));
}

/** Field names the dashboard pages and server actions have always used (camelCase), mapped from the API's snake_case. */
export function toProfile(profile: ProfileData) {
  return {
    id: profile.id,
    email: profile.email,
    emailVerified: profile.email_verified,
    displayName: profile.display_name,
    bio: profile.bio,
    avatarUrl: profile.avatar_url,
    location: profile.location,
    website: profile.website,
    phoneNumber: profile.phone_number,
    createdAt: profile.created_at,
  };
}

export function toSettings(settings: SettingsData) {
  return {
    theme: settings.theme,
    emailNotifications: settings.email_notifications,
    language: settings.language,
    timezone: settings.timezone,
  };
}

export function toLoginHistoryEntry(entry: HistoryEntry) {
  return {
    id: entry.id,
    ipAddress: entry.ip_address,
    userAgent: entry.user_agent,
    location: entry.location,
    loginAt: entry.login_at,
    successful: entry.successful,
  };
}
