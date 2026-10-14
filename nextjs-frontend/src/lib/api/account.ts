import 'server-only';

import { callBackend } from './server';
import {
  createSession,
  deleteSession,
  readHistory,
  readProfile,
  readSession,
  readSettings,
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

export function revokeBackendSession() {
  return callBackend((client) => deleteSession({ client }));
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
