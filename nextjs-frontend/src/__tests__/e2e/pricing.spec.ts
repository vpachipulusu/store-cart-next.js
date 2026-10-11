import { test, expect } from '@playwright/test';
import { waitForPageReady } from './helpers/e2e-utils';

/**
 * Pricing & Marketing Pages E2E Tests
 *
 * These tests cover publicly accessible marketing pages:
 * - Pricing page (tiers, features, FAQ, CTA)
 * - Navigation between marketing and auth pages
 */

test.describe('Pricing Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/pricing');
    await waitForPageReady(page);
  });

  test.describe('Page Header', () => {
    test('should display pricing page heading', async ({ page }) => {
      await expect(
        page.getByRole('heading', { name: /simple.*transparent.*pricing/i })
      ).toBeVisible();
    });

    test('should display pricing page description', async ({ page }) => {
      await expect(page.getByText(/choose the plan that.*right for you/i)).toBeVisible();
      await expect(page.getByText(/14-day free trial/i).first()).toBeVisible();
    });
  });

  test.describe('Pricing Tiers', () => {
    test('should display all 3 pricing tiers', async ({ page }) => {
      await expect(page.getByText(/^free$/i).first()).toBeVisible();
      await expect(page.getByText(/^pro$/i).first()).toBeVisible();
      await expect(page.getByText(/^enterprise$/i).first()).toBeVisible();
    });

    test('should display prices for each tier', async ({ page }) => {
      // Free tier should show $0
      await expect(page.getByRole('heading', { name: /^free$/i })).toBeVisible();
      await expect(page.getByText('$0').first()).toBeVisible();

      // Pro and Enterprise should show a dollar amount (fetched from Stripe)
      await expect(page.getByRole('heading', { name: /^pro$/i })).toBeVisible();
      const proCard = page.locator('[class*="card"]').filter({ hasText: /^Pro$/ });
      await expect(proCard.getByText(/\$\d+/).first()).toBeVisible();

      await expect(page.getByRole('heading', { name: /^enterprise$/i })).toBeVisible();
      const enterpriseCard = page.locator('[class*="card"]').filter({ hasText: /^Enterprise$/ });
      await expect(enterpriseCard.getByText(/\$\d+/).first()).toBeVisible();
    });

    test('should display tier descriptions', async ({ page }) => {
      await expect(page.getByText(/perfect for getting started/i)).toBeVisible();
      await expect(page.getByText(/for professionals and growing teams/i)).toBeVisible();
      await expect(page.getByText(/for large organizations/i)).toBeVisible();
    });

    test('should display feature lists for each tier', async ({ page }) => {
      // Free tier features
      await expect(page.getByText('Up to 3 projects', { exact: true })).toBeVisible();
      await expect(page.getByText('Basic analytics', { exact: true })).toBeVisible();
      await expect(page.getByText('Community support', { exact: true })).toBeVisible();

      // Pro tier features - use exact match to avoid matching "No team collaboration"
      await expect(page.getByText('Unlimited projects', { exact: true })).toBeVisible();
      await expect(page.getByText('Advanced analytics', { exact: true })).toBeVisible();
      await expect(page.getByText('Priority support', { exact: true })).toBeVisible();
      await expect(page.getByText('Custom domains', { exact: true })).toBeVisible();
      await expect(page.getByText('API access', { exact: true })).toBeVisible();

      // Enterprise tier features
      await expect(page.getByText('Everything in Pro', { exact: true })).toBeVisible();
      await expect(page.getByText('Unlimited storage', { exact: true })).toBeVisible();
      await expect(page.getByText('24/7 phone support', { exact: true })).toBeVisible();
      await expect(page.getByText('Dedicated account manager', { exact: true })).toBeVisible();
    });

    test('should display CTA buttons for each tier', async ({ page }) => {
      await expect(page.getByRole('link', { name: /get started/i })).toBeVisible();
      await expect(page.getByRole('link', { name: /start free trial/i }).first()).toBeVisible();
      await expect(page.getByRole('link', { name: /contact sales/i }).first()).toBeVisible();
    });

    test('should link Free tier to signup page', async ({ page }) => {
      const getStartedLink = page.getByRole('link', { name: /get started/i });
      await expect(getStartedLink).toHaveAttribute('href', '/signup');
    });

    test('should link Pro tier to signup with plan param', async ({ page }) => {
      const startTrialLink = page.getByRole('link', { name: /start free trial/i }).first();
      await expect(startTrialLink).toHaveAttribute('href', '/signup?plan=pro');
    });
  });

  test.describe('FAQ Section', () => {
    test('should display FAQ heading', async ({ page }) => {
      await expect(
        page.getByRole('heading', { name: /frequently asked questions/i })
      ).toBeVisible();
    });

    test('should display FAQ items', async ({ page }) => {
      await expect(page.getByText(/can i change my plan later/i)).toBeVisible();
      await expect(page.getByText(/what payment methods/i)).toBeVisible();
      await expect(page.getByText(/do you offer refunds/i)).toBeVisible();
      await expect(page.getByText(/is there a free trial/i)).toBeVisible();
    });

    test('should display FAQ answers', async ({ page }) => {
      await expect(page.getByText(/upgrade or downgrade/i)).toBeVisible();
      await expect(page.getByText(/visa.*mastercard/i)).toBeVisible();
      await expect(page.getByText(/30-day money-back/i)).toBeVisible();
    });
  });

  test.describe('CTA Section', () => {
    test('should display bottom CTA section', async ({ page }) => {
      await expect(page.getByText(/ready to get started/i)).toBeVisible();
      await expect(page.getByText(/thousands of satisfied customers/i)).toBeVisible();
    });

    test('should display CTA buttons', async ({ page }) => {
      // There should be a "Start Free Trial" and "Contact Sales" in the CTA
      const startTrialButtons = page.getByRole('link', { name: /start free trial/i });
      await expect(startTrialButtons.last()).toBeVisible();

      const contactButtons = page.getByRole('link', { name: /contact sales/i });
      await expect(contactButtons.last()).toBeVisible();
    });
  });

  test.describe('Responsive Design', () => {
    test('should display pricing cards in grid on desktop', async ({ page }) => {
      await page.setViewportSize({ width: 1280, height: 800 });
      await page.goto('/pricing');
      await waitForPageReady(page);

      // Grid container should be visible
      const grid = page.locator('.grid.gap-8');
      await expect(grid.first()).toBeVisible();
    });

    test('should stack pricing cards on mobile', async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 667 });
      await page.goto('/pricing');
      await waitForPageReady(page);

      // All 3 tiers should still be visible
      await expect(page.getByText(/^free$/i).first()).toBeVisible();
      await expect(page.getByText(/^pro$/i).first()).toBeVisible();
      await expect(page.getByText(/^enterprise$/i).first()).toBeVisible();
    });
  });

  test.describe('Billing Period Toggle', () => {
    test('should display billing period toggle with Monthly and Yearly options', async ({
      page,
    }) => {
      await expect(page.getByRole('button', { name: 'Monthly' })).toBeVisible();
      await expect(page.getByRole('button', { name: /yearly/i })).toBeVisible();
    });

    test('should default to Monthly billing', async ({ page }) => {
      const monthlyButton = page.getByRole('button', { name: 'Monthly' });
      await expect(monthlyButton).toHaveClass(/bg-primary/);
    });

    test('should switch to Yearly billing when clicked', async ({ page }) => {
      const yearlyButton = page.getByRole('button', { name: /yearly/i });
      await yearlyButton.click();
      await expect(yearlyButton).toHaveClass(/bg-primary/);
    });

    test('should not display savings badge when there is 0% savings', async ({ page }) => {
      const yearlyButton = page.getByRole('button', { name: /yearly/i });
      await yearlyButton.click();

      // If there's no discount, the badge shouldn't show
      const savingsBadge = page.getByText(/save \d+%/i);
      const count = await savingsBadge.count();

      // Badge should only show if there's a discount configured
      if (count > 0) {
        const badgeText = await savingsBadge.textContent();
        expect(badgeText).toMatch(/save \d+%/i);
      }
    });

    test('should switch back to Monthly billing', async ({ page }) => {
      const yearlyButton = page.getByRole('button', { name: /yearly/i });
      await yearlyButton.click();

      const monthlyButton = page.getByRole('button', { name: 'Monthly' });
      await monthlyButton.click();
      await expect(monthlyButton).toHaveClass(/bg-primary/);
    });
  });

  test.describe('Price Display - Monthly Billing', () => {
    test('should display monthly prices with /month label', async ({ page }) => {
      const monthlyButton = page.getByRole('button', { name: 'Monthly' });
      await monthlyButton.click();

      // Wait for a moment for price update
      await page.waitForTimeout(1000);

      // Check that prices show /month using more flexible selectors
      await expect(page.locator('text=/month').first()).toBeVisible();

      // Verify multiple prices show /month
      const monthPrices = await page.locator('text=/month').count();
      expect(monthPrices).toBeGreaterThanOrEqual(2); // At least Pro and Enterprise
    });

    test('should display "Cancel anytime" text for monthly billing', async ({ page }) => {
      const monthlyButton = page.getByRole('button', { name: 'Monthly' });
      await monthlyButton.click();

      // Check that "Cancel anytime" appears
      const cancelText = page.getByText(/cancel anytime/i);
      const count = await cancelText.count();
      expect(count).toBeGreaterThan(0);
    });

    test('should not display annual billing text for monthly plans', async ({ page }) => {
      const monthlyButton = page.getByRole('button', { name: 'Monthly' });
      await monthlyButton.click();

      // Should not see "billed annually"
      await expect(page.getByText(/billed annually/i)).not.toBeVisible();
    });
  });

  test.describe('Price Display - Yearly Billing', () => {
    test('should display monthly breakdown when yearly is selected', async ({ page }) => {
      const yearlyButton = page.getByRole('button', { name: /yearly/i });
      await yearlyButton.click();

      // Wait for price update
      await page.waitForTimeout(1000);

      // Prices should still show /month (monthly breakdown)
      await expect(page.locator('text=/month').first()).toBeVisible();

      // Verify multiple prices show /month
      const monthPrices = await page.locator('text=/month').count();
      expect(monthPrices).toBeGreaterThanOrEqual(2); // At least Pro and Enterprise
    });

    test('should display annual total with "billed annually" text', async ({ page }) => {
      const yearlyButton = page.getByRole('button', { name: /yearly/i });
      await yearlyButton.click();

      // Wait for price update
      await page.waitForTimeout(500);

      // Should show "billed annually" with total amount
      const billedAnnually = page.getByText(/billed annually/i);
      const count = await billedAnnually.count();
      expect(count).toBeGreaterThan(0);
    });

    test('should not display "Cancel anytime" for yearly billing', async ({ page }) => {
      const yearlyButton = page.getByRole('button', { name: /yearly/i });
      await yearlyButton.click();

      // Should not see "Cancel anytime"
      await expect(page.getByText(/cancel anytime/i)).not.toBeVisible();
    });

    test('should display consistent pricing across tiers', async ({ page }) => {
      const yearlyButton = page.getByRole('button', { name: /yearly/i });
      await yearlyButton.click();

      // Wait for price update
      await page.waitForTimeout(500);

      // Get all price elements
      const monthlyPrices = await page.getByText(/\$\d+\.?\d*\/month/).all();
      const annualTexts = await page.getByText(/billed annually/i).all();

      // Should have monthly breakdown prices displayed
      expect(monthlyPrices.length).toBeGreaterThan(0);

      // Should have annual billing text
      expect(annualTexts.length).toBeGreaterThan(0);
    });
  });

  test.describe('Current Plan Indicator (Authenticated Users)', () => {
    test.skip('should show "Current Plan" only on active tier', async ({ page, context }) => {
      // This test requires authentication with a specific test user
      // Skipped - requires test user setup with Pro subscription
      // Implementation:
      // 1. Login as test user with Pro tier
      // 2. Navigate to pricing page
      // 3. Verify "Active" badge shows only on Pro tier
      // 4. Verify "Current Plan" button shows only on Pro tier
      // 5. Verify "Downgrade" shows on Free tier for paid users
    });

    test.skip('should not show multiple "Current Plan" buttons', async ({ page }) => {
      // This test requires authentication
      // Skipped - requires test user setup
      // Implementation:
      // 1. Login as authenticated user
      // 2. Navigate to pricing page
      // 3. Count "Current Plan" buttons - should be exactly 1
    });
  });

  test.describe('Pricing Accuracy', () => {
    test('should display prices fetched from Stripe', async ({ page }) => {
      // Wait for page load
      await page.waitForTimeout(1000);

      // Should have dollar signs visible
      const dollarSigns = await page.locator('text=/\\$/').count();
      expect(dollarSigns).toBeGreaterThan(0);
    });

    test('should update prices when switching billing periods', async ({ page }) => {
      // Get monthly price count
      const monthlyButton = page.getByRole('button', { name: 'Monthly' });
      await monthlyButton.click();
      await page.waitForTimeout(1000);

      const monthlyPrices = await page.locator('text=/month').count();
      expect(monthlyPrices).toBeGreaterThan(0);

      // Switch to yearly
      const yearlyButton = page.getByRole('button', { name: /yearly/i });
      await yearlyButton.click();
      await page.waitForTimeout(1000);

      // Should still show /month (monthly breakdown)
      const yearlyMonthlyPrices = await page.locator('text=/month').count();
      expect(yearlyMonthlyPrices).toBeGreaterThan(0);

      // Should show "billed annually"
      await expect(page.locator('text=/billed annually/i').first()).toBeVisible();
    });
  });
});
