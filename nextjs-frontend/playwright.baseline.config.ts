import { defineConfig } from '@playwright/test';
import baseConfig from './playwright.config';

/**
 * KAN-113 behaviour baseline: Chromium only, against a production build.
 *
 * `next dev` compiles each route on first request. Under parallel workers that pushed page loads and redirects past
 * the test timeouts, so the baseline runs `next build && next start` instead. Run with `npm run test:e2e:baseline`.
 */
export default defineConfig({
  ...baseConfig,
  projects: (baseConfig.projects ?? []).filter(
    (project) => project.name === 'setup' || project.name === 'chromium'
  ),
  webServer: {
    command: 'npm run build && npm run start',
    url: 'http://localhost:3000',
    reuseExistingServer: !process.env.CI,
    timeout: 600_000,
  },
});
