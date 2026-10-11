/**
 * Next.js Proxy (formerly Middleware)
 *
 * Handles authentication, rate limiting, and request processing
 * Note: Migrated from middleware.ts to proxy.ts for Next.js 16+
 */

import { NextRequest, NextResponse } from 'next/server';
import {
  rateLimit,
  getRateLimitHeaders,
  RATE_LIMIT_CONFIGS,
  RateLimitConfig,
} from '@/lib/middleware/rate-limit';

/**
 * Get client identifier for rate limiting
 */
function getClientIdentifier(request: NextRequest): string {
  // Use forwarded IP if behind proxy
  const forwardedFor = request.headers.get('x-forwarded-for');
  if (forwardedFor) {
    return forwardedFor.split(',')[0].trim();
  }

  // Use real IP
  const realIp = request.headers.get('x-real-ip');
  if (realIp) {
    return realIp;
  }

  // Fallback to connection IP
  return 'unknown';
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
  } else if (pathname.startsWith('/api/webhooks/')) {
    rateLimitConfig = RATE_LIMIT_CONFIGS.webhook;
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

    // Enforce email verification for protected routes
    const emailVerified = request.cookies.get('email-verified')?.value;
    if (emailVerified === 'false') {
      const verifyUrl = new URL('/verify-email', request.url);
      return NextResponse.redirect(verifyUrl);
    }
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
  const publicApiRoutes = ['/api/webhooks/', '/api/health'];
  const isPublicApiRoute = publicApiRoutes.some((route) => pathname.startsWith(route));

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
  const response = NextResponse.next();

  // Security headers
  response.headers.set('X-Content-Type-Options', 'nosniff');
  response.headers.set('X-Frame-Options', 'DENY');
  response.headers.set('X-XSS-Protection', '1; mode=block');
  response.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');

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
  ],
};
