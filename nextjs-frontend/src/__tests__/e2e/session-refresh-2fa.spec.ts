import type { Page } from '@playwright/test';
import { test, expect } from './helpers/fixtures';
import {
  loginAsThrowawayAccount,
  useDistinctClientIp,
  waitForPageReady,
} from './helpers/e2e-utils';

/**
 * KAN-183: the session refresh goes through POST /v1/auth/session/refresh, and the security page shows the
 * real two-factor status from `two_factor_enabled` on the API profile. Needs the FastAPI backend (BACKEND_API_URL).
 * A rejected refresh cannot be provoked from the browser (the backend still refreshed with a sign-in over 5 minutes
 * old), so that path is covered by the unit tests in auth-actions-security.test.ts and use-session-refresh.test.tsx.
 */

async function sessionCookieValue(page: Page): Promise<string | undefined> {
  return (await page.context().cookies()).find((cookie) => cookie.name === 'session')?.value;
}

test.describe('Session refresh and 2FA status (KAN-183)', () => {
  test.beforeEach(async ({ page }) => {
    await useDistinctClientIp(page);
  });

  test('security page shows that two-factor authentication is not enabled', async ({
    page,
    throwawayAccount,
  }) => {
    await loginAsThrowawayAccount(page, throwawayAccount);
    await page.goto('/dashboard/security');
    await waitForPageReady(page);

    await expect(page.getByText('Two-Factor Authentication', { exact: true })).toBeVisible();
    await expect(page.getByTestId('two-factor-status')).toHaveText(
      'Two-factor authentication is not enabled'
    );
  });

  test('a refresh issues a new session cookie through the API and keeps the user signed in', async ({
    page,
    throwawayAccount,
  }) => {
    await loginAsThrowawayAccount(page, throwawayAccount);
    const before = await sessionCookieValue(page);
    expect(before).toBeTruthy();

    // Session cookies carry their issue time in whole seconds; make sure a re-issued one differs.
    await page.waitForTimeout(1_500);
    // Loading a dashboard page makes the session provider refresh with the current Firebase ID token.
    await page.goto('/dashboard/security');
    await waitForPageReady(page);

    await expect.poll(() => sessionCookieValue(page)).not.toBe(before);
    await expect(page).toHaveURL(/\/dashboard\/security/);
    await expect(page.getByTestId('two-factor-status')).toBeVisible();
  });
});
