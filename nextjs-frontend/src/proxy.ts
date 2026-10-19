/**
 * Next.js Proxy (formerly Middleware)
 *
 * Handles authentication, rate limiting, and request processing
 * Note: Migrated from middleware.ts to proxy.ts for Next.js 16+
 */

import { NextRequest, NextResponse } from 'next/server';
import { getClientIdentifier } from '@/lib/middleware/client-identifier';
import {
  rateLimit,
  getRateLimitHeaders,
  RATE_LIMIT_CONFIGS,
  RateLimitConfig,
} from '@/lib/middleware/rate-limit';
import {
  isInternalStorefrontPath,
  isStorefrontPathPreviewEnabled,
  parseStorePath,
  parseStoreSlug,
  resolvePlatformRootDomain,
  STORE_NOT_FOUND_SLUG,
  STORE_SLUG_HEADER,
  STOREFRONT_PREVIEW_ROUTE,
  STOREFRONT_ROUTE,
} from '@/lib/storefront/host';

/** Security headers shared by every response the proxy lets through. */
function applySecurityHeaders(response: NextResponse): void {
  response.headers.set('X-Content-Type-Options', 'nosniff');
  response.headers.set('X-Frame-Options', 'DENY');
  response.headers.set('X-XSS-Protection', '1; mode=block');
  response.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');
}

/**
 * KAN-64: `{slug}.<PLATFORM_ROOT_DOMAIN>` is a store. Rewrite every path on that host under the internal
 * `/storefront/{slug}` route, so root-domain routes (dashboard, admin, API) are never reachable from a store
 * host. The proxy does not call the backend; the pages look the store up and 404 unknown or suspended ones.
 */
function rewriteToStorefront(request: NextRequest, slug: string, headers: Headers): NextResponse {
  const url = request.nextUrl.clone();
  url.pathname = `${STOREFRONT_ROUTE}/${slug}${url.pathname === '/' ? '' : url.pathname}`;
  headers.set(STORE_SLUG_HEADER, slug);
  const response = NextResponse.rewrite(url, { request: { headers } });
  applySecurityHeaders(response);
  response.headers.set('Content-Security-Policy', STORE_HOST_CONTENT_SECURITY_POLICY);
  return response;
}

/**
 * Baseline for store hosts (KAN-75), which render merchant text: no plugins, no <base> hijack, no framing, no form
 * posts off the host. Scripts stay as Next.js needs them (inline bootstrap), so this limits, not forbids, script.
 */
const STORE_HOST_CONTENT_SECURITY_POLICY =
  "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'";

/** The internal 404 page: a fresh URL, so no query string or trailing-slash state of the request survives. */
function notFoundTarget(request: NextRequest): URL {
  return new URL(`${STOREFRONT_PREVIEW_ROUTE}/${STORE_NOT_FOUND_SLUG}`, request.url);
}

/**
 * KAN-75: the storefront pages are cached per store and cannot read request headers, so the proxy is what keeps
 * them off the platform origin. A direct `/storefront/...` or `/storefront-preview/...` request (not a store host,
 * not `/s`) is rewritten to the internal 404 without the slug marker.
 */
function rejectInternalStorefrontPath(request: NextRequest, headers: Headers): NextResponse {
  const response = NextResponse.rewrite(notFoundTarget(request), { request: { headers } });
  applySecurityHeaders(response);
  response.headers.set('X-Robots-Tag', 'noindex');
  return response;
}

const PREVIEW_CONTENT_SECURITY_POLICY = "default-src 'none'; style-src 'unsafe-inline'";

/**
 * KAN-202 (temporary): preview-only `/s/{slug}`. When enabled and the slug is valid it is rewritten like a
 * store host; only the store root is served (no sub-routes exist). In every other case (flag off,
 * production, sub-path, malformed or reserved slug) it is rewritten to the internal 404 target without the
 * slug marker, so the response is the same 404 as an unknown store. All responses are noindex. Remove with
 * the wildcard domain.
 */
function rewritePathPreview(
  request: NextRequest,
  preview: { slug: string | null; rest: string },
  headers: Headers
): NextResponse {
  const slug =
    preview.rest === '' &&
    isStorefrontPathPreviewEnabled({
      STOREFRONT_PATH_PREVIEW: process.env.STOREFRONT_PATH_PREVIEW,
      VERCEL_ENV: process.env.VERCEL_ENV,
      NODE_ENV: process.env.NODE_ENV,
    })
      ? preview.slug
      : null;
  let url: URL;
  if (slug) {
    url = request.nextUrl.clone();
    url.pathname = `${STOREFRONT_PREVIEW_ROUTE}/${slug}`;
    headers.set(STORE_SLUG_HEADER, slug);
  } else {
    url = notFoundTarget(request);
  }
  const response = NextResponse.rewrite(url, { request: { headers } });
  applySecurityHeaders(response);
  response.headers.set('X-Robots-Tag', 'noindex');
  // /s shares the dashboard and admin origin, so nothing a store page renders may run script or load resources.
  response.headers.set('Content-Security-Policy', PREVIEW_CONTENT_SECURITY_POLICY);
  return response;
}

/**
 * Apply rate limiting to request
 */
function applyRateLimit(request: NextRequest, pathname: string): NextResponse | null {
  const identifier = getClientIdentifier(request);

  let rateLimitConfig: RateLimitConfig = RATE_LIMIT_CONFIGS.general;

  // Apply different rate limits based on path
  if (pathname.startsWith('/api/auth/')) {
    rateLimitConfig = RATE_LIMIT_CONFIGS.auth;
  } else if (pathname.startsWith('/api/')) {
    rateLimitConfig = RATE_LIMIT_CONFIGS.api;
  }

  const result = rateLimit(identifier, rateLimitConfig);

  if (!result.success) {
    return NextResponse.json(
      { error: result.message || 'Too many requests' },
      {
        status: 429,
        headers: getRateLimitHeaders(result),
      }
    );
  }

  return null;
}

/**
 * Main proxy function (Next.js 16+ convention)
 * Note: Function must be named "proxy" for Next.js 16+
 */
export async function proxy(request: NextRequest) {
  const pathname = request.nextUrl.pathname;

  // The slug marker is proxy-only: drop any client-supplied copy before anything else sees the request.
  const forwardedHeaders = new Headers(request.headers);
  forwardedHeaders.delete(STORE_SLUG_HEADER);

  const storeSlug = parseStoreSlug(
    request.headers.get('host'),
    resolvePlatformRootDomain(process.env.PLATFORM_ROOT_DOMAIN)
  );
  if (storeSlug) {
    return rewriteToStorefront(request, storeSlug, forwardedHeaders);
  }

  const pathPreview = parseStorePath(pathname);
  if (pathPreview) {
    return rewritePathPreview(request, pathPreview, forwardedHeaders);
  }

  if (isInternalStorefrontPath(pathname)) {
    return rejectInternalStorefrontPath(request, forwardedHeaders);
  }

  // Apply rate limiting to API routes
  if (pathname.startsWith('/api/')) {
    const rateLimitResponse = applyRateLimit(request, pathname);
    if (rateLimitResponse) {
      return rateLimitResponse;
    }
  }

  // Auth pages that should redirect if user is already authenticated
  const authPages = ['/login', '/signup'];
  const isAuthPage = authPages.some((route) => pathname.startsWith(route));
  const authToken = request.cookies.get('session');

  if (isAuthPage && authToken) {
    // Redirect authenticated users away from auth pages to dashboard
    const dashboardUrl = new URL('/dashboard', request.url);
    return NextResponse.redirect(dashboardUrl);
  }

  // Protected routes that require authentication
  const protectedRoutes = ['/dashboard', '/settings', '/profile', '/security'];
  const isProtectedRoute = protectedRoutes.some((route) => pathname.startsWith(route));

  if (isProtectedRoute) {
    // Check for authentication cookie or session
    if (!authToken) {
      // Redirect to login if not authenticated
      const loginUrl = new URL('/login', request.url);
      loginUrl.searchParams.set('redirect', pathname);
      return NextResponse.redirect(loginUrl);
    }

    // Email verification is NOT decided here (KAN-123). The edge cannot verify Firebase tokens, and the
    // `email-verified` cookie is client-writable, so it must never gate access. The signed
    // `email_verified` claim is enforced server-side by `@/lib/auth/verified-session`, which the
    // dashboard/admin layouts, server actions and admin helpers call.
  }

  // Admin routes
  const isAdminRoute = pathname.startsWith('/admin');

  if (isAdminRoute) {
    const authToken = request.cookies.get('session');

    if (!authToken) {
      const loginUrl = new URL('/login', request.url);
      loginUrl.searchParams.set('redirect', pathname);
      return NextResponse.redirect(loginUrl);
    }

    // Admin role verification would be done in the API route or page
    // as we can't easily verify Firebase tokens in edge middleware
  }

  // Public API routes (no auth required)
  const publicApiExact = ['/api/health'];
  const isPublicApiRoute = publicApiExact.includes(pathname);

  // Protected API routes (require authentication)
  if (pathname.startsWith('/api/') && !isPublicApiRoute) {
    const authHeader = request.headers.get('authorization');

    if (!authHeader || !authHeader.startsWith('Bearer ')) {
      // Check for cookie-based auth as fallback
      const authToken = request.cookies.get('session');

      if (!authToken) {
        return NextResponse.json(
          { error: 'Unauthorized: Authentication required' },
          { status: 401 }
        );
      }
    }
  }

  // Add security headers
  const response = NextResponse.next({ request: { headers: forwardedHeaders } });
  applySecurityHeaders(response);

  // CORS headers for API routes
  if (pathname.startsWith('/api/')) {
    response.headers.set('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
    response.headers.set('Access-Control-Allow-Headers', 'Content-Type, Authorization');
    response.headers.set('Access-Control-Max-Age', '86400');
  }

  return response;
}

/**
 * Proxy configuration
 * Defines which routes this proxy should handle
 */
export const config = {
  matcher: [
    /*
     * Match all request paths except:
     * - _next/static (static files)
     * - _next/image (image optimization files)
     * - favicon.ico (favicon file)
     * - public files (images, etc.)
     */
    '/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)',
    // KAN-75: the image-suffix exclusion above must never let a direct internal storefront path skip the guard.
    '/storefront/:path*',
    '/storefront-preview/:path*',
  ],
};
