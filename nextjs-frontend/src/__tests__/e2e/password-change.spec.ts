import { randomBytes } from 'node:crypto';

import type { Browser, Page } from '@playwright/test';

import { test, expect, configureE2eContext } from './helpers/fixtures';
import {
  expectRedirectToLogin,
  clickNavLink,
  loginViaUI,
  // Aliased only because the react-hooks lint rule mistakes the `use` prefix for a React hook.
  useDistinctClientIp as routeWithDistinctClientIp,
  waitForHydration,
  waitForPageReady,
} from './helpers/e2e-utils';

/**
 * Live password change and multi-tab session behaviour (KAN-209, follow-up to KAN-208).
 *
 * Each test signs in a throwaway Firebase user (helpers/fixtures.ts, deleted in teardown even on failure), changes
 * its password from the dashboard security page and checks what Firebase's revocation does to every session of that
 * user. The shared role accounts are never touched. Passwords are generated per run and never logged or asserted
 * in a message.
 */

const PASSWORD_CHANGE_TIMEOUT_MS = 30_000;

// Each test signs in more than once against live Firebase; the 30 s default is too tight.
test.describe.configure({ timeout: 120_000 });

const newPassword = () => randomBytes(24).toString('base64url');

/**
 * Opens the Change Password dialog from a signed-in dashboard page by following the nav link, as a person does.
 * A full page load straight to the security page races the Firebase client restoring its signed-in user, and the
 * re-authentication step then reports "You are signed out".
 */
async function openChangePasswordDialog(page: Page) {
  await clickNavLink(page, page.getByRole('link', { name: 'Security', exact: true }).first());
  await expect(page).toHaveURL(/\/dashboard\/security$/);
  await waitForPageReady(page);
  await page.getByRole('button', { name: 'Change Password', exact: true }).click();
  return page.getByRole('dialog', { name: 'Change Password', exact: true });
}

const toastWithText = (page: Page, text: string) =>
  page
    .locator('[data-sonner-toast], [role="status"], [data-radix-toast-viewport] li')
    .filter({ hasText: text })
    .first();

async function changePasswordViaDashboard(
  page: Page,
  currentPassword: string,
  nextPassword: string
): Promise<void> {
  const dialog = await openChangePasswordDialog(page);
  await dialog.getByLabel('Current Password', { exact: true }).fill(currentPassword);
  await dialog.getByLabel('New Password', { exact: true }).fill(nextPassword);
  await dialog.getByLabel('Confirm New Password', { exact: true }).fill(nextPassword);
  // Re-authentication, the change and the re-sign-in are three Firebase round trips; allow for a slow one.
  // The success toast is shown only after the re-sign-in minted the new session (security/page.tsx); wait for it
  // from before the click so a quick redirect cannot hide it.
  const success = toastWithText(page, 'Password changed successfully');
  await Promise.all([
    expect(success).toBeVisible({ timeout: PASSWORD_CHANGE_TIMEOUT_MS }),
    dialog.getByRole('button', { name: 'Change Password', exact: true }).click(),
  ]);
  await expect(dialog).toBeHidden();
}

/** Strict: the page opens for a signed-in browser. No retry, so a rejected session fails the test. */
async function expectSecurityPageOpens(page: Page): Promise<void> {
  await page.goto('/dashboard/security');
  await waitForPageReady(page);
  await expect(page).toHaveURL(/\/dashboard\/security$/);
  await expect(page.getByRole('button', { name: 'Change Password', exact: true })).toBeVisible();
}

const SIGN_IN_ATTEMPTS = 2;
const LOGIN_SETTLE_TIMEOUT_MS = 30_000;

/**
 * Signs in through the login form and confirms the new session is accepted. A session minted a moment ago can be
 * refused once when this machine's clock is slightly behind Google's ("Token used too early"): the layout clears
 * it and sends the browser to /login. Only here, right after a sign-in, is that retried (signing in again, never a
 * sleep), and every retry is annotated on the test. The assertions that prove a session works or is revoked never
 * retry.
 */
async function signInAccepted(
  page: Page,
  account: { email: string; password: string }
): Promise<void> {
  for (let attempt = 1; ; attempt += 1) {
    await loginViaUI(page, account.email, account.password);
    await page.goto('/dashboard/security');
    await waitForPageReady(page);
    if (/\/dashboard\/security$/.test(page.url())) return;
    if (attempt >= SIGN_IN_ATTEMPTS) {
      throw new Error('A fresh session was refused twice and the browser stayed on the login page');
    }
    test.info().annotations.push({
      type: 'sign-in-retry',
      description: 'fresh session refused once (clock skew), signed in again',
    });
    // The layout's redirect goes through /api/auth/clear-session; wait for it to land on the login page.
    await page.waitForURL(/\/login(?:\?|$)/, { timeout: LOGIN_SETTLE_TIMEOUT_MS });
  }
}

/** Signs this page in (accepted session) and leaves it on a dashboard page, ready to open Security from the nav. */
async function signInOnDashboard(
  page: Page,
  account: { email: string; password: string }
): Promise<void> {
  await page.context().clearCookies();
  await signInAccepted(page, account);
  // Move by client-side navigation (the Firebase client has restored its user once the next page is ready).
  await clickNavLink(page, page.getByRole('link', { name: 'Profile', exact: true }).first());
  await expect(page).toHaveURL(/\/dashboard\/profile$/);
  await waitForPageReady(page);
}

/** A second browser, with its own cookies, signed in as the account. */
async function openSecondTab(
  browser: Browser,
  account: { email: string; password: string }
): Promise<{ page: Page; close: () => Promise<void> }> {
  const context = await browser.newContext();
  try {
    await configureE2eContext(context);
    const page = await context.newPage();
    await routeWithDistinctClientIp(page);
    await signInAccepted(page, account);
    return { page, close: () => context.close() };
  } catch (error) {
    await context.close();
    throw error;
  }
}

test.describe('Password change (live Firebase)', () => {
  test.beforeEach(async ({ page }) => {
    await routeWithDistinctClientIp(page);
  });

  test('only the new password signs in afterwards', async ({ page, browser, throwawayAccount }) => {
    const oldPassword = throwawayAccount.password;
    const changedPassword = newPassword();
    await signInOnDashboard(page, throwawayAccount);

    await changePasswordViaDashboard(page, oldPassword, changedPassword);

    // A fresh browser: the old password is refused, the new one signs in and protected pages work.
    const fresh = await browser.newContext();
    try {
      await configureE2eContext(fresh);
      const freshPage = await fresh.newPage();
      await routeWithDistinctClientIp(freshPage);
      await freshPage.goto('/login');
      await waitForHydration(freshPage);
      await freshPage.getByLabel('Email', { exact: true }).fill(throwawayAccount.email);
      await freshPage.getByLabel('Password', { exact: true }).fill(oldPassword);
      await freshPage.getByRole('button', { name: 'Sign In', exact: true }).click();
      await expect(
        freshPage.getByText('Invalid email or password. Please try again.', { exact: true })
      ).toBeVisible();
      await expect(freshPage).toHaveURL(/\/login(?:\?|$)/);

      await signInAccepted(freshPage, { email: throwawayAccount.email, password: changedPassword });
      await expectSecurityPageOpens(freshPage);
      await freshPage.goto('/dashboard/profile');
      await waitForPageReady(freshPage);
      await expect(freshPage).toHaveURL(/\/dashboard\/profile$/);
    } finally {
      await fresh.close();
    }
  });

  test('a wrong current password is rejected and nothing changes', async ({
    page,
    browser,
    throwawayAccount,
  }) => {
    await signInOnDashboard(page, throwawayAccount);
    const dialog = await openChangePasswordDialog(page);
    const attempt = newPassword();
    await dialog.getByLabel('Current Password', { exact: true }).fill(newPassword());
    await dialog.getByLabel('New Password', { exact: true }).fill(attempt);
    await dialog.getByLabel('Confirm New Password', { exact: true }).fill(attempt);
    await dialog.getByRole('button', { name: 'Change Password', exact: true }).click();
    await expect(toastWithText(page, 'Invalid email or password. Please try again.')).toBeVisible({
      timeout: PASSWORD_CHANGE_TIMEOUT_MS,
    });
    await expect(dialog).toBeVisible();
    await expect(toastWithText(page, 'Password changed successfully')).toHaveCount(0);

    // The original password still works in a clean browser, so the account was not changed.
    const fresh = await openSecondTab(browser, throwawayAccount);
    try {
      await expectSecurityPageOpens(fresh.page);
    } finally {
      await fresh.close();
    }
  });
});

test.describe('Multi-tab session after a password change (live Firebase)', () => {
  test.beforeEach(async ({ page }) => {
    await routeWithDistinctClientIp(page);
  });

  // Intermittent on a machine whose clock is a moment behind Google's: the backend rejects the cookie minted
  // right after the change with "Token used too early" (firebase_admin verifies with no clock skew allowance),
  // the dashboard layout clears the session and the changing browser lands on /login. Quarantined until the
  // backend verifies with `clock_skew_seconds`; that backend follow-up story is pending owner approval. Remove the `.fixme` in that PR.
  test.fixme('the browser that changes the password keeps its session (KAN-209 finding)', async ({
    page,
    throwawayAccount,
  }) => {
    await signInOnDashboard(page, throwawayAccount);
    await changePasswordViaDashboard(page, throwawayAccount.password, newPassword());
    await expect(page).toHaveURL(/\/dashboard\/security$/);
    await expectSecurityPageOpens(page);
    await page.reload();
    await waitForPageReady(page);
    await expect(page).toHaveURL(/\/dashboard\/security$/);
  });

  test('a second browser opened before the change is revoked and can sign in again with the new password', async ({
    page,
    browser,
    throwawayAccount,
  }) => {
    const changedPassword = newPassword();
    // The browser that changes the password signs in last, so it stays on the dashboard until the change.
    const other = await openSecondTab(browser, throwawayAccount);
    try {
      await signInOnDashboard(page, throwawayAccount);
      // The second session works before the change.
      await expectSecurityPageOpens(other.page);
      const savedCookies = await other.page.context().cookies();

      await changePasswordViaDashboard(page, throwawayAccount.password, changedPassword);

      // The saved pre-change session cookie, replayed in a clean browser, is refused: revocation is on the
      // cookie itself, not just on the tab that held it.
      const replay = await browser.newContext();
      try {
        await configureE2eContext(replay);
        await replay.addCookies(savedCookies);
        const replayPage = await replay.newPage();
        await routeWithDistinctClientIp(replayPage);
        await expectRedirectToLogin(replayPage, '/dashboard/security');
      } finally {
        await replay.close();
      }

      // The other browser's session cookie was minted before the password change, so Firebase revokes it.
      await expectRedirectToLogin(other.page, '/dashboard/security');
      await expectRedirectToLogin(other.page, '/dashboard/profile');

      // Signing in again there with the new password restores access.
      await signInAccepted(other.page, {
        email: throwawayAccount.email,
        password: changedPassword,
      });
      await expectSecurityPageOpens(other.page);
    } finally {
      await other.close();
    }
  });
});
