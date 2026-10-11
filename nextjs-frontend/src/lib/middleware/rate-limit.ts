/**
 * Rate Limiting Middleware
 *
 * Implements token bucket algorithm for rate limiting
 * Stores rate limit data in memory (use Redis in production)
 */

interface RateLimitStore {
  tokens: number;
  lastRefill: number;
}

const rateLimitStore = new Map<string, RateLimitStore>();

export interface RateLimitConfig {
  maxRequests: number;
  windowMs: number;
  message?: string;
}

export interface RateLimitResult {
  success: boolean;
  limit: number;
  remaining: number;
  reset: number;
  message?: string;
}

/**
 * Token bucket rate limiter
 * @param identifier - Unique identifier (e.g., IP address, user ID)
 * @param config - Rate limit configuration
 */
export function rateLimit(
  identifier: string,
  config: RateLimitConfig
): RateLimitResult {
  const now = Date.now();
  const { maxRequests, windowMs, message } = config;

  // Get or create store entry
  let store = rateLimitStore.get(identifier);

  if (!store) {
    store = {
      tokens: maxRequests,
      lastRefill: now,
    };
    rateLimitStore.set(identifier, store);
  }

  // Calculate tokens to add based on time elapsed
  const timePassed = now - store.lastRefill;
  const refillRate = maxRequests / windowMs;
  const tokensToAdd = Math.floor(timePassed * refillRate);

  // Refill tokens
  if (tokensToAdd > 0) {
    store.tokens = Math.min(maxRequests, store.tokens + tokensToAdd);
    store.lastRefill = now;
  }

  // Calculate reset time
  const reset = now + windowMs;

  // Check if request is allowed
  if (store.tokens >= 1) {
    store.tokens -= 1;
    return {
      success: true,
      limit: maxRequests,
      remaining: Math.floor(store.tokens),
      reset,
    };
  }

  // Rate limit exceeded
  return {
    success: false,
    limit: maxRequests,
    remaining: 0,
    reset,
    message: message || 'Too many requests. Please try again later.',
  };
}

/**
 * Clean up old entries from the rate limit store
 * Should be called periodically to prevent memory leaks
 */
export function cleanupRateLimitStore(maxAge: number = 3600000): void {
  const now = Date.now();

  for (const [key, store] of rateLimitStore.entries()) {
    if (now - store.lastRefill > maxAge) {
      rateLimitStore.delete(key);
    }
  }
}

/**
 * Get rate limit headers for response
 */
export function getRateLimitHeaders(result: RateLimitResult): Record<string, string> {
  return {
    'X-RateLimit-Limit': result.limit.toString(),
    'X-RateLimit-Remaining': result.remaining.toString(),
    'X-RateLimit-Reset': new Date(result.reset).toISOString(),
  };
}

/**
 * Preset configurations for common endpoints
 */
export const RATE_LIMIT_CONFIGS = {
  // Strict limits for auth endpoints
  auth: {
    maxRequests: 5,
    windowMs: 15 * 60 * 1000, // 15 minutes
    message: 'Too many authentication attempts. Please try again in 15 minutes.',
  },
  // Standard API limits
  api: {
    maxRequests: 100,
    windowMs: 60 * 1000, // 1 minute
    message: 'API rate limit exceeded. Please slow down.',
  },
  // Webhook limits
  webhook: {
    maxRequests: 200,
    windowMs: 60 * 1000, // 1 minute
    message: 'Webhook rate limit exceeded.',
  },
  // General limits
  general: {
    maxRequests: 200,
    windowMs: 60 * 1000, // 1 minute
    message: 'Too many requests. Please try again later.',
  },
} as const;

// Cleanup interval (every hour)
if (typeof window === 'undefined') {
  setInterval(() => cleanupRateLimitStore(), 3600000);
}
