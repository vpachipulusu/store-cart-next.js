/**
 * Invitation links carry a single-use token in the path (`/invite/<token>`, KAN-62). Sentry events, transactions and
 * breadcrumbs record URLs, route names and request headers, so they are scrubbed before they leave the process.
 * Shared by the server, edge and client Sentry configs; safe to import from client code.
 *
 * - Copy on write: the input is never modified (breadcrumbs can carry the app's live objects).
 * - Only arrays and plain objects are descended into, with a cycle guard and a depth cap.
 * - Fail closed: if scrubbing throws, the event or breadcrumb is dropped (a credential may be in it).
 */

/** `/invite/` or its URL-encoded form, then the token up to the next delimiter. */
const INVITE_TOKEN = /((?:\/|%2f)invite(?:\/|%2f))[^/?#%\s"'<>]+/gi;
export const INVITE_TOKEN_PLACEHOLDER = '[token]';
const MAX_DEPTH = 12;
const TRUNCATED = '[Truncated]';
const CIRCULAR = '[Circular]';
/**
 * Next.js router headers on server-action and RSC requests. The state tree holds the dynamic segment value (the
 * token) on its own, outside any `/invite/` path, so these are removed rather than scrubbed.
 */
const ROUTER_HEADERS: ReadonlySet<string> = new Set([
  'next-router-state-tree',
  'next-url',
  'next-router-segment-prefetch',
]);

export function scrubInviteTokenText(text: string): string {
  return text.replace(INVITE_TOKEN, `$1${INVITE_TOKEN_PLACEHOLDER}`);
}

function isPlainObject(value: object): value is Record<string, unknown> {
  const prototype: unknown = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function scrub(value: unknown, depth: number, seen: WeakSet<object>): unknown {
  if (typeof value === 'string') return scrubInviteTokenText(value);
  if (value === null || typeof value !== 'object') return value;
  if (!Array.isArray(value) && !isPlainObject(value)) return value;
  if (seen.has(value)) return CIRCULAR;
  if (depth >= MAX_DEPTH) return TRUNCATED;
  seen.add(value);
  if (Array.isArray(value)) return value.map((item) => scrub(item, depth + 1, seen));
  const copy: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) copy[key] = scrub(item, depth + 1, seen);
  return copy;
}

/** A scrubbed copy of any JSON-like value; the input is left untouched. */
export function scrubInviteTokens<T>(value: T): T {
  return scrub(value, 0, new WeakSet()) as T;
}

function withoutRouterHeaders(event: Record<string, unknown>): void {
  const request = event.request;
  if (!request || typeof request !== 'object') return;
  const headers = (request as Record<string, unknown>).headers;
  if (!headers || typeof headers !== 'object') return;
  const record = headers as Record<string, unknown>;
  for (const name of Object.keys(record)) {
    if (ROUTER_HEADERS.has(name.toLowerCase())) delete record[name];
  }
}

/** `beforeSend` / `beforeSendTransaction`: a scrubbed copy without router headers, or null when scrubbing fails. */
export function scrubSentryEvent<T extends object>(event: T): T | null {
  try {
    const copy = scrubInviteTokens(event) as T & Record<string, unknown>;
    withoutRouterHeaders(copy);
    return copy;
  } catch {
    return null;
  }
}

/**
 * `beforeBreadcrumb`: console breadcrumbs keep only their (scrubbed) message, since `data.arguments` holds whatever
 * the app logged. Null (dropped) when scrubbing fails.
 */
export function scrubBreadcrumb<T extends { category?: string; data?: unknown }>(
  breadcrumb: T
): T | null {
  try {
    if (
      breadcrumb.category === 'console' &&
      breadcrumb.data &&
      typeof breadcrumb.data === 'object'
    ) {
      const { arguments: _logged, ...data } = breadcrumb.data as Record<string, unknown>;
      return scrubInviteTokens({ ...breadcrumb, data });
    }
    return scrubInviteTokens(breadcrumb);
  } catch {
    return null;
  }
}

/** The hooks every Sentry config spreads into `Sentry.init` (server, edge and client). */
export const INVITE_TOKEN_SENTRY_HOOKS = {
  beforeSend: scrubSentryEvent,
  beforeSendTransaction: scrubSentryEvent,
  beforeBreadcrumb: scrubBreadcrumb,
} as const;
