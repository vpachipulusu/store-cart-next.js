import { test as setup } from '@playwright/test';

/**
 * Global setup for Playwright tests.
 * This runs before all test projects and can be used to seed test data,
 * authenticate test users, or prepare the environment.
 *
 * For authenticated tests, individual specs use helper functions
 * to set session cookies directly, avoiding flaky Firebase auth flows.
 */
setup('verify test environment', async ({ page }) => {
  // Verify the app is reachable
  const response = await page.goto('/');
  if (!response || !response.ok()) {
    throw new Error(
      `App not reachable at http://localhost:3000. Status: ${response?.status()}`
    );
  }
});
