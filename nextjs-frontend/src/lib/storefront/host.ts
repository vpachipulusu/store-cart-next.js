/**
 * Store subdomain detection (KAN-64). Pure string logic, safe for the proxy.
 *
 * `{slug}.<root>` is a store host. Anything else (the root itself, reserved names, nested labels, IP hosts,
 * look-alike domains, malformed values) is not, so it falls through to the normal app. The slug rules mirror
 * the backend (`app/core/slugs.py`): 3 to 63 chars of `a-z0-9` and single hyphens. The backend stays the
 * authority on which slugs are live stores; this only decides whether to ask it.
 */

export const DEFAULT_PLATFORM_ROOT_DOMAIN = 'localhost';

const SLUG_MIN_LENGTH = 3;
const SLUG_MAX_LENGTH = 63;
const SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const HOST_PATTERN = /^[a-z0-9.-]+$/;
const PORT_PATTERN = /^\d{1,5}$/;

/** Copy of the backend's RESERVED_SLUGS: names that are platform hosts and never stores. */
export const RESERVED_SLUGS: ReadonlySet<string> = new Set([
  'www',
  'admin',
  'api',
  'app',
  'mail',
  'email',
  'smtp',
  'imap',
  'pop',
  'ftp',
  'ns1',
  'ns2',
  'dns',
  'static',
  'assets',
  'cdn',
  'media',
  'dashboard',
  'console',
  'help',
  'support',
  'docs',
  'blog',
  'status',
  'login',
  'logout',
  'signin',
  'signup',
  'auth',
  'account',
  'billing',
  'checkout',
  'cart',
  'webhooks',
  'internal',
  'root',
  'localhost',
  'staging',
  'dev',
  'test',
  'preview',
  'store',
  'stores',
  'shop',
  'storecart',
  'postmaster',
  'abuse',
  'hostmaster',
  'webmaster',
  'noreply',
  'security',
  'mx',
  'vpn',
  'git',
  'ssl',
  'web',
  'webmail',
  'autodiscover',
  'sandbox',
  'demo',
  'prod',
  'production',
  'payments',
  'pay',
  'portal',
  'about',
  'pricing',
  'terms',
  'privacy',
  'legal',
  'contact',
  'careers',
  'stripe',
  'firebase',
  'vercel',
]);

/** Splits `host[:port]`; null for anything that is not a plain ASCII DNS name with an optional numeric port. */
function normaliseHost(value: string): string | null {
  const lower = value.trim().toLowerCase();
  const colon = lower.indexOf(':');
  const name = colon === -1 ? lower : lower.slice(0, colon);
  if (colon !== -1 && !PORT_PATTERN.test(lower.slice(colon + 1))) return null;
  const withoutDot = name.endsWith('.') ? name.slice(0, -1) : name;
  return withoutDot && HOST_PATTERN.test(withoutDot) ? withoutDot : null;
}

let warnedRootDomain = false;

/**
 * The configured platform root domain (`PLATFORM_ROOT_DOMAIN`), normalised; `localhost` when unset or invalid.
 * In production that fallback means store subdomains silently stop working, so it warns once (never throws,
 * and uses console because the proxy bundle must not import the Winston logger).
 */
export function resolvePlatformRootDomain(value: string | undefined): string {
  const resolved = value ? normaliseHost(value) : null;
  if (resolved) return resolved;
  if (process.env.NODE_ENV === 'production' && !warnedRootDomain) {
    warnedRootDomain = true;
    console.warn(
      '[storefront] PLATFORM_ROOT_DOMAIN is unset or invalid; falling back to "localhost", so store subdomains will not resolve.'
    );
  }
  return DEFAULT_PLATFORM_ROOT_DOMAIN;
}

export function isValidStoreSlug(slug: string): boolean {
  return (
    slug.length >= SLUG_MIN_LENGTH &&
    slug.length <= SLUG_MAX_LENGTH &&
    SLUG_PATTERN.test(slug) &&
    !RESERVED_SLUGS.has(slug)
  );
}

/** The store slug for a Host header under `rootDomain`, or null when the host is not a store host. */
export function parseStoreSlug(
  hostHeader: string | null | undefined,
  rootDomain: string
): string | null {
  if (!hostHeader) return null;
  const host = normaliseHost(hostHeader);
  const suffix = `.${rootDomain}`;
  if (!host || !host.endsWith(suffix)) return null;
  const label = host.slice(0, -suffix.length);
  return isValidStoreSlug(label) ? label : null;
}

/**
 * KAN-202 (temporary): preview-only `/s/{slug}` access for deployments without a wildcard domain, such as
 * `*.vercel.app`. Remove with the proxy branch and the e2e spec once the wildcard domain exists.
 */
export const STORE_PATH_PREFIX = '/s';

/**
 * Internal 404 target for `/s/*` requests that are not served. The underscore makes it an invalid slug
 * (never a real store), so the route 404s.
 */
export const STORE_NOT_FOUND_SLUG = 'not_found';

/**
 * Allow-list, fail closed. Preview paths are served only when `STOREFRONT_PATH_PREVIEW` is exactly `true` and
 * `VERCEL_ENV` is `preview` or `development`, or `VERCEL_ENV` is unset and `NODE_ENV` is not `production`.
 * Production, an unset `VERCEL_ENV` under a production build (self-hosted production, or Vercel system env
 * vars switched off), empty and unknown values are all disabled. Stricter than "not production" on purpose.
 */
export function isStorefrontPathPreviewEnabled(env: {
  STOREFRONT_PATH_PREVIEW?: string;
  VERCEL_ENV?: string;
  NODE_ENV?: string;
}): boolean {
  if (env.STOREFRONT_PATH_PREVIEW !== 'true') return false;
  if (env.VERCEL_ENV === 'preview' || env.VERCEL_ENV === 'development') return true;
  return env.VERCEL_ENV === undefined && env.NODE_ENV !== 'production';
}

/**
 * Splits `/s/{slug}[/rest]`. Null when the path is not under the preview prefix; `slug` is null when the
 * segment is missing, malformed or reserved (same validator as host routing). Paths are case-sensitive, so
 * `/s/Acme` is malformed rather than lower-cased.
 */
export function parseStorePath(pathname: string): { slug: string | null; rest: string } | null {
  if (pathname !== STORE_PATH_PREFIX && !pathname.startsWith(`${STORE_PATH_PREFIX}/`)) return null;
  const remainder = pathname.slice(STORE_PATH_PREFIX.length + 1);
  const slash = remainder.indexOf('/');
  const segment = slash === -1 ? remainder : remainder.slice(0, slash);
  const rest = slash === -1 ? '' : remainder.slice(slash);
  return { slug: isValidStoreSlug(segment) ? segment : null, rest };
}

/**
 * Internal request header the proxy sets to the store slug it rewrote to. The storefront route only renders
 * when it matches the path slug, so `/storefront/<slug>` on any other host is a 404. The proxy deletes any
 * client-supplied copy first, so it cannot be forged.
 */
export const STORE_SLUG_HEADER = 'x-storefront-slug';
