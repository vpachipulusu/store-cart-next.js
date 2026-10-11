/**
 * Lightweight IP geolocation lookup
 * Uses ip-api.com free tier (non-commercial, 45 req/min)
 * For production, consider a paid service or local GeoIP database
 */

import { logger } from '@/lib/logger';

export async function getLocationFromIP(ip: string): Promise<string | null> {
  // Skip private/local IPs
  if (
    !ip ||
    ip === 'unknown' ||
    ip === '127.0.0.1' ||
    ip === '::1' ||
    ip.startsWith('192.168.') ||
    ip.startsWith('10.') ||
    ip.startsWith('172.')
  ) {
    return 'Local Network';
  }

  try {
    const response = await fetch(
      `http://ip-api.com/json/${ip}?fields=country,regionName,city`,
      { signal: AbortSignal.timeout(3000) }
    );

    if (!response.ok) return null;

    const data = await response.json();
    if (data.city && data.country) {
      return `${data.city}, ${data.country}`;
    }
    if (data.country) {
      return data.country;
    }

    return null;
  } catch (error) {
    logger.error('Geo IP lookup failed:', error);
    return null;
  }
}
