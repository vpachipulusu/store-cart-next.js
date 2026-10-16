import type { Page } from '@playwright/test';
import { test, expect } from './helpers/fixtures';
import { loginAsThrowawayAccount, waitForPageReady } from './helpers/e2e-utils';

/**
 * KAN-61: the dashboard is scoped to the selected store and merchants with several stores can switch.
 *
 * Needs the FastAPI backend (BACKEND_API_URL) and BACKEND_INTERNAL_KEY in the environment. Organisations and
 * stores are created through the real API with the throwaway account's own session; a free plan allows one store
 * per organisation, so the two stores live in two organisations (the switcher spans organisations).
 */

async function createOrganizationWithStore(
  page: Page,
  label: string,
  suffix: string
): Promise<string> {
  const session = (await page.context().cookies()).find((cookie) => cookie.name === 'session');
  const internalKey = process.env.BACKEND_INTERNAL_KEY;
  if (!session || !internalKey) {
    throw new Error('Seeding stores needs the session cookie and BACKEND_INTERNAL_KEY');
  }
  const backendUrl = (process.env.BACKEND_API_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '');
  const headers = {
    'Content-Type': 'application/json',
    'X-Internal-Key': internalKey,
    'X-Session-Token': session.value,
  };
  const slugBase = `e2e-${suffix}-${label}`.toLowerCase().replace(/[^a-z0-9-]/g, '-');

  const org = await fetch(`${backendUrl}/v1/organizations`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ name: `Org ${label}`, slug: slugBase }),
  });
  if (!org.ok) throw new Error(`Creating organisation ${label} failed (HTTP ${org.status})`);
  const organizationId = ((await org.json()) as { data: { id: string } }).data.id;

  const store = await fetch(`${backendUrl}/v1/organizations/${organizationId}/stores`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ name: `Store ${label}`, slug: `${slugBase}-shop` }),
  });
  if (!store.ok) throw new Error(`Creating store ${label} failed (HTTP ${store.status})`);
  return `Store ${label}`;
}

test.describe('Dashboard store switcher', () => {
  test.skip(
    !process.env.BACKEND_INTERNAL_KEY,
    'Skipped: BACKEND_INTERNAL_KEY / BACKEND_API_URL not set (needs FastAPI)'
  );

  test('scopes the dashboard to a store and switches between several', async ({
    page,
    throwawayAccount,
  }) => {
    const suffix = throwawayAccount.email.split('@')[0].slice(-12);
    await loginAsThrowawayAccount(page, throwawayAccount);

    // Zero stores: /dashboard redirects to onboarding (KAN-210), so check the empty state on a page that
    // does not: an empty state, no switcher, and the profile page still renders.
    await page.goto('/dashboard/profile');
    await waitForPageReady(page);
    await expect(page.getByTestId('no-stores')).toBeVisible();
    await expect(page.getByTestId('store-switcher')).toHaveCount(0);
    await expect(page).toHaveURL(/\/dashboard\/profile$/);
    await expect(page.getByRole('heading', { name: 'Profile', level: 1 })).toBeVisible();

    // One store: its name is shown, with no switcher chrome.
    const alpha = await createOrganizationWithStore(page, 'alpha', suffix);
    await page.goto('/dashboard');
    await waitForPageReady(page);
    await expect(page.getByTestId('store-name')).toHaveText(alpha);
    await expect(page.getByTestId('store-switcher')).toHaveCount(0);
    await expect(page.getByTestId('no-stores')).toHaveCount(0);

    // Several stores: a labelled 44px switcher that defaults to the first store.
    const beta = await createOrganizationWithStore(page, 'beta', suffix);
    await page.goto('/dashboard');
    await waitForPageReady(page);
    const switcher = page.getByRole('combobox', { name: 'Switch store' });
    await expect(switcher).toBeVisible();
    const box = await switcher.boundingBox();
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
    const first = (await switcher.textContent())?.trim() ?? '';
    expect([alpha, beta]).toContain(first);
    const other = first === alpha ? beta : alpha;

    // Switch with the keyboard, and the choice survives navigation and a reload.
    await switcher.focus();
    await page.keyboard.press('Enter');
    await page.getByRole('option', { name: new RegExp(other) }).click();
    await expect(switcher).toHaveText(other);
    await expect(page.locator('main[data-store-id]')).toBeVisible();

    await page.goto('/dashboard/profile');
    await waitForPageReady(page);
    await expect(page.getByRole('combobox', { name: 'Switch store' })).toHaveText(other);

    await page.reload();
    await waitForPageReady(page);
    await expect(page.getByRole('combobox', { name: 'Switch store' })).toHaveText(other);

    // A forged cookie naming a store the user cannot open falls back to the first store.
    await page.context().clearCookies({ name: 'selected-store' });
    await page.context().addCookies([
      {
        name: 'selected-store',
        value: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
        url: page.url(),
      },
    ]);
    await page.goto('/dashboard');
    await waitForPageReady(page);
    await expect(page.getByRole('combobox', { name: 'Switch store' })).toHaveText(first);

    // Phone width: the header does not overflow and the switcher stays inside the viewport.
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto('/dashboard');
    await waitForPageReady(page);
    const narrow = await page.getByRole('combobox', { name: 'Switch store' }).boundingBox();
    expect((narrow?.x ?? 0) + (narrow?.width ?? 0)).toBeLessThanOrEqual(375);
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(scrollWidth).toBeLessThanOrEqual(375);
  });
});
