import type { Page } from '@playwright/test';
import * as OTPAuth from 'otpauth';

import { test, expect } from './helpers/fixtures';
import {
  expectToast,
  loginAsThrowawayAccount,
  loginAsThrowawayAccountWithOrganization,
  useDistinctClientIp,
  waitForPageReady,
} from './helpers/e2e-utils';

/**
 * KAN-180: account deletion and 2FA disable ask the user to re-authenticate (password re-entry here; OAuth users
 * get the provider popup, which cannot run in e2e) and pass the fresh Firebase ID token to the server action.
 * 2FA enrolment stays hidden until sign-in enforces 2FA (KAN-125, parked). Needs the FastAPI backend
 * (BACKEND_API_URL) and BACKEND_INTERNAL_KEY, like the organisation and billing specs.
 */

const BACKEND_URL = (process.env.BACKEND_API_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '');
const OWNER_CONFLICT = 'Transfer organization ownership before deleting your account';

async function openDeleteDialog(page: Page) {
  await page.goto('/dashboard/security');
  await waitForPageReady(page);
  await page.getByRole('button', { name: 'Delete Account', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Delete Account', exact: true });
  await expect(dialog).toBeVisible();
  return dialog;
}

/** Enables TOTP for the signed-in throwaway account through the backend and returns its authenticator. */
async function enableTwoFactor(
  page: Page,
  account: { email: string; password: string }
): Promise<OTPAuth.TOTP> {
  const apiKey = process.env.NEXT_PUBLIC_FIREBASE_API_KEY;
  const internalKey = process.env.BACKEND_INTERNAL_KEY;
  const session = (await page.context().cookies()).find((cookie) => cookie.name === 'session');
  if (!apiKey || !internalKey || !session) {
    throw new Error(
      'Enabling 2FA needs NEXT_PUBLIC_FIREBASE_API_KEY, BACKEND_INTERNAL_KEY and a session'
    );
  }
  const signIn = await fetch(
    `https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=${apiKey}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: account.email,
        password: account.password,
        returnSecureToken: true,
      }),
    }
  );
  const { idToken } = (await signIn.json()) as { idToken?: string };
  if (!signIn.ok || !idToken) throw new Error(`Fresh sign-in failed with HTTP ${signIn.status}`);

  const headers = {
    'Content-Type': 'application/json',
    'X-Internal-Key': internalKey,
    'X-Session-Token': session.value,
  };
  const enroll = await fetch(`${BACKEND_URL}/v1/me/totp/enroll`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ id_token: idToken }),
  });
  if (!enroll.ok) throw new Error(`TOTP enrol failed with HTTP ${enroll.status}`);
  const { data } = (await enroll.json()) as { data: { secret: string } };
  const authenticator = new OTPAuth.TOTP({
    algorithm: 'SHA1',
    digits: 6,
    period: 30,
    secret: OTPAuth.Secret.fromBase32(data.secret),
  });
  const verify = await fetch(`${BACKEND_URL}/v1/me/totp/verify`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ token: authenticator.generate() }),
  });
  if (!verify.ok) throw new Error(`TOTP verify failed with HTTP ${verify.status}`);
  return authenticator;
}

test.describe('Re-authentication dialog (KAN-180)', () => {
  test.beforeEach(async ({ page }) => {
    await useDistinctClientIp(page);
  });

  test('2FA enrolment is not offered while sign-in does not enforce it', async ({
    page,
    throwawayAccount,
  }) => {
    await loginAsThrowawayAccount(page, throwawayAccount);
    await page.goto('/dashboard/security');
    await waitForPageReady(page);

    await expect(page.getByTestId('two-factor-status')).toHaveText(
      'Two-factor authentication is not enabled'
    );
    await expect(page.getByRole('button', { name: /enable 2fa/i })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /disable 2fa/i })).toHaveCount(0);
  });

  test('delete account needs DELETE and the password, and a wrong password keeps the account', async ({
    page,
    throwawayAccount,
  }) => {
    await loginAsThrowawayAccount(page, throwawayAccount);
    const dialog = await openDeleteDialog(page);
    const confirm = dialog.getByRole('button', { name: 'Delete Account', exact: true });

    await expect(confirm).toBeDisabled();
    await dialog.getByLabel('Type DELETE to confirm', { exact: true }).fill('DELETE');
    await expect(confirm).toBeDisabled();
    await dialog.getByLabel('Confirm your password', { exact: true }).fill('Wrong-Password-1!');
    await confirm.click();

    await expect(dialog.getByRole('alert')).toBeVisible();
    await expect(dialog).toBeVisible();
    await expect(page).toHaveURL(/\/dashboard\/security/);
    // The password field is emptied after an attempt; nothing is kept in the page.
    await expect(dialog.getByLabel('Confirm your password', { exact: true })).toHaveValue('');
    await page.reload();
    await waitForPageReady(page);
    await expect(page).toHaveURL(/\/dashboard\/security/);
  });

  test('cancelling the delete dialog clears what was typed', async ({ page, throwawayAccount }) => {
    await loginAsThrowawayAccount(page, throwawayAccount);
    const dialog = await openDeleteDialog(page);
    await dialog.getByLabel('Type DELETE to confirm', { exact: true }).fill('DELETE');
    await dialog.getByLabel('Confirm your password', { exact: true }).fill('something');
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
    await expect(dialog).not.toBeVisible();

    await page.getByRole('button', { name: 'Delete Account', exact: true }).click();
    const reopened = page.getByRole('dialog', { name: 'Delete Account', exact: true });
    await expect(reopened.getByLabel('Type DELETE to confirm', { exact: true })).toHaveValue('');
    await expect(reopened.getByLabel('Confirm your password', { exact: true })).toHaveValue('');
  });

  test('an organisation owner sees the transfer-ownership message and keeps the account', async ({
    page,
    throwawayAccount,
  }) => {
    await loginAsThrowawayAccountWithOrganization(page, throwawayAccount);
    const dialog = await openDeleteDialog(page);
    await dialog.getByLabel('Type DELETE to confirm', { exact: true }).fill('DELETE');
    await dialog
      .getByLabel('Confirm your password', { exact: true })
      .fill(throwawayAccount.password);
    await dialog.getByRole('button', { name: 'Delete Account', exact: true }).click();

    await expect(dialog.getByRole('alert')).toHaveText(OWNER_CONFLICT);
    await page.reload();
    await waitForPageReady(page);
    await expect(page).toHaveURL(/\/dashboard\/security/);
  });

  test('disable 2FA re-authenticates, checks the code and turns 2FA off', async ({
    page,
    throwawayAccount,
  }) => {
    test.skip(!process.env.BACKEND_INTERNAL_KEY, 'BACKEND_INTERNAL_KEY is not configured');
    await loginAsThrowawayAccount(page, throwawayAccount);
    const authenticator = await enableTwoFactor(page, throwawayAccount);
    await page.goto('/dashboard/security');
    await waitForPageReady(page);
    await expect(page.getByTestId('two-factor-status')).toHaveText(
      'Two-factor authentication is enabled'
    );

    await page.getByRole('button', { name: 'Disable 2FA', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'Disable Two-Factor Authentication' });
    const confirm = dialog.getByRole('button', { name: 'Disable 2FA', exact: true });
    const code = dialog.getByLabel('Authenticator code', { exact: true });
    const password = dialog.getByLabel('Confirm your password', { exact: true });
    await expect(confirm).toBeDisabled();

    // A wrong password is refused by Firebase before any code is sent.
    await code.fill(authenticator.generate());
    await password.fill('Wrong-Password-1!');
    await confirm.click();
    await expect(dialog.getByRole('alert')).toBeVisible();

    // The right password with an invalid code is refused by the API.
    let invalid = '000000';
    while (authenticator.validate({ token: invalid, window: 1 }) !== null) {
      invalid = String(Number(invalid) + 1).padStart(6, '0');
    }
    await code.fill(invalid);
    await password.fill(throwawayAccount.password);
    await confirm.click();
    await expect(dialog.getByRole('alert')).toHaveText('Invalid authenticator code');

    await code.fill(authenticator.generate());
    await password.fill(throwawayAccount.password);
    await confirm.click();
    await expectToast(page, 'Two-factor authentication disabled');
    await expect(dialog).not.toBeVisible();
    await page.reload();
    await waitForPageReady(page);
    await expect(page.getByTestId('two-factor-status')).toHaveText(
      'Two-factor authentication is not enabled'
    );
  });
});
