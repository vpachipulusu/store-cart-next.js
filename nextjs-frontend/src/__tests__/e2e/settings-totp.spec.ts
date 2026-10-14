import * as OTPAuth from 'otpauth';

import { test, expect } from './helpers/fixtures';
import {
  expectToast,
  loginAsThrowawayAccount,
  useDistinctClientIp,
  waitForPageReady,
} from './helpers/e2e-utils';

test.describe('Legacy settings and authenticator setup', () => {
  test('persists account preferences after reloading', async ({ page, throwawayAccount }) => {
    await useDistinctClientIp(page);
    await loginAsThrowawayAccount(page, throwawayAccount);
    await page.goto('/dashboard/settings');
    await waitForPageReady(page);
    const theme = page.getByRole('combobox', { name: 'Theme', exact: true });
    await expect(theme).toBeVisible();
    await theme.click();
    await page.getByRole('option', { name: 'Dark', exact: true }).click();
    const notifications = page.getByRole('switch', { name: 'Email Notifications' });
    await expect(notifications).toBeChecked();
    await notifications.click();
    await page.getByRole('combobox', { name: 'Language', exact: true }).click();
    await page.getByRole('option', { name: 'Français', exact: true }).click();
    await page.getByRole('combobox', { name: 'Timezone', exact: true }).click();
    await page.getByRole('option', { name: 'Paris (CET)', exact: true }).click();
    await page.getByRole('button', { name: 'Save Settings', exact: true }).click();
    await expectToast(page, 'Settings updated successfully');
    await page.reload();
    await waitForPageReady(page);
    await expect(theme).toHaveText('Dark');
    await expect(notifications).not.toBeChecked();
    await expect(page.getByRole('combobox', { name: 'Language', exact: true })).toHaveText(
      'Français'
    );
    await expect(page.getByRole('combobox', { name: 'Timezone', exact: true })).toHaveText(
      'Paris (CET)'
    );
  });

  // KAN-41: authenticator setup/disable is switched off (KAN-180 re-authentication dialog; hidden while KAN-125
  // is parked).
  test.skip('rejects an invalid authenticator code, enables and then disables setup', async ({
    page,
    throwawayAccount,
  }) => {
    await useDistinctClientIp(page);
    await loginAsThrowawayAccount(page, throwawayAccount);
    await page.goto('/dashboard/security');
    await waitForPageReady(page);
    await expect(
      page.getByText('Two-factor authentication is not enabled', { exact: true })
    ).toBeVisible();
    await page.getByRole('button', { name: 'Enable 2FA', exact: true }).click();
    const enrollment = page.getByRole('dialog', { name: 'Enable Two-Factor Authentication' });
    await expect(enrollment.getByAltText('2FA QR Code')).toBeVisible();
    const secretInput = enrollment.locator('input[readonly]');
    const secret = await secretInput.inputValue();
    if (!/^[A-Z2-7]+$/.test(secret)) throw new Error('Enrollment did not show a TOTP secret');
    const authenticator = new OTPAuth.TOTP({
      algorithm: 'SHA1',
      digits: 6,
      period: 30,
      secret: OTPAuth.Secret.fromBase32(secret),
    });
    // Exclude all accepted drift-window codes, rather than guessing that 000000 is invalid.
    let invalid = '000000';
    while (authenticator.validate({ token: invalid, window: 1 }) !== null) {
      invalid = String(Number(invalid) + 1).padStart(6, '0');
    }
    const code = enrollment.getByLabel('Enter the 6-digit code from your app:');
    await code.fill(invalid);
    await enrollment.getByRole('button', { name: 'Verify & Enable', exact: true }).click();
    await expectToast(page, /Invalid verification code/i);
    await expect(enrollment).toBeVisible();
    await code.fill(authenticator.generate());
    await enrollment.getByRole('button', { name: 'Verify & Enable', exact: true }).click();
    await expectToast(page, 'Two-factor authentication enabled successfully!');
    await expect(enrollment).not.toBeVisible();
    await page.reload();
    await waitForPageReady(page);
    await expect(
      page.getByText('Two-factor authentication is enabled', { exact: true })
    ).toBeVisible();
    await expect(page.locator('input[readonly]')).toHaveCount(0);
    await expect(page.getByAltText('2FA QR Code')).toHaveCount(0);
    await page.getByRole('button', { name: 'Disable 2FA', exact: true }).click();
    const disable = page.getByRole('dialog', { name: 'Disable Two-Factor Authentication' });
    await disable
      .getByLabel('Enter the 6-digit code from your authenticator app:')
      .fill(authenticator.generate());
    await disable.getByRole('button', { name: 'Disable 2FA', exact: true }).click();
    await expectToast(page, 'Two-factor authentication disabled successfully');
    await expect(disable).not.toBeVisible();
    await page.reload();
    await waitForPageReady(page);
    await expect(
      page.getByText('Two-factor authentication is not enabled', { exact: true })
    ).toBeVisible();
  });

  test('shows the existing avatar upload placeholder', async ({ page, throwawayAccount }) => {
    await useDistinctClientIp(page);
    await loginAsThrowawayAccount(page, throwawayAccount);
    await page.goto('/dashboard/profile');
    await waitForPageReady(page);
    await expect(page.getByText('Upload Photo', { exact: true })).toBeVisible();
    await page.locator('#avatar-upload').setInputFiles({
      name: 'avatar.png',
      mimeType: 'image/png',
      buffer: Buffer.from(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZ9kAAAAASUVORK5CYII=',
        'base64'
      ),
    });
    await expectToast(
      page,
      'Avatar upload would happen here. Integrate with your storage service.'
    );
  });
});
