/**
 * Invitation links carry a single-use token in the path (`/invite/<token>`, KAN-62). Sentry events, transactions and
 * breadcrumbs record URLs and route names, so every string in them is scrubbed before it leaves the process.
 * Shared by the server, edge and client Sentry configs; safe to import from client code.
 */

const INVITE_TOKEN = /(\/invite\/)[^/?#\s"'<>]+/g;
export const INVITE_TOKEN_PLACEHOLDER = '[token]';
const MAX_DEPTH = 12;

export function scrubInviteTokenText(text: string): string {
  return text.replace(INVITE_TOKEN, `$1${INVITE_TOKEN_PLACEHOLDER}`);
}

function scrub(value: unknown, depth: number): unknown {
  if (typeof value === 'string') return scrubInviteTokenText(value);
  if (depth >= MAX_DEPTH || value === null || typeof value !== 'object') return value;
  if (Array.isArray(value)) {
    for (let index = 0; index < value.length; index += 1) {
      value[index] = scrub(value[index], depth + 1);
    }
    return value;
  }
  const record = value as Record<string, unknown>;
  for (const key of Object.keys(record)) {
    record[key] = scrub(record[key], depth + 1);
  }
  return record;
}

/** Scrubs in place and returns the same object, as Sentry's `beforeSend` hooks expect. */
export function scrubInviteTokens<T>(event: T): T {
  return scrub(event, 0) as T;
}
