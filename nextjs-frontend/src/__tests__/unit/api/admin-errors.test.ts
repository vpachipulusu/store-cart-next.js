// @vitest-environment node
/**
 * KAN-50: the shared admin error mapping picks a curated message by status only, and a page can name what a
 * 404 means.
 */
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/headers', () => ({ cookies: vi.fn(), headers: vi.fn() }));

import {
  ADMIN_FORBIDDEN_MESSAGE,
  ADMIN_NOT_FOUND_MESSAGE,
  ADMIN_REQUEST_FAILED_MESSAGE,
  ADMIN_UNAVAILABLE_MESSAGE,
  adminErrorMessage,
} from '@/lib/api/admin-errors';
import {
  ADMIN_USER_NOT_FOUND_MESSAGE,
  adminErrorMessage as userError,
} from '@/lib/api/admin-users';

const fail = (status?: number) => ({ success: false as const, error: 'SECRET', status });

describe('adminErrorMessage', () => {
  it.each([
    [401, ADMIN_FORBIDDEN_MESSAGE],
    [403, ADMIN_FORBIDDEN_MESSAGE],
    [404, ADMIN_NOT_FOUND_MESSAGE],
    [500, ADMIN_REQUEST_FAILED_MESSAGE],
    [undefined, ADMIN_UNAVAILABLE_MESSAGE],
  ])('maps status %s to a curated message', (status, expected) => {
    expect(adminErrorMessage(fail(status))).toBe(expected);
  });

  it('uses the caller-supplied wording for a 404', () => {
    expect(adminErrorMessage(fail(404), 'Order not found')).toBe('Order not found');
  });

  it('keeps the users pages saying "User not found"', () => {
    expect(userError(fail(404))).toBe(ADMIN_USER_NOT_FOUND_MESSAGE);
    expect(userError(fail(403))).toBe(ADMIN_FORBIDDEN_MESSAGE);
  });
});
