import { defineConfig } from '@playwright/test';
import baseConfig from './playwright.config';

/**
 * Specs for the flows Foundation keeps (KAN-113 scope, approved by the PO).
 * homepage, currency and pricing specs stay in the repo but are outside the baseline gate.
 */
const GATED_SPECS = [
  'auth',
  'session-expiry',
  'dashboard',
  'subscription',
  'subscription-simple',
  'billing-management',
  'admin',
] as const;

const GATED_SPEC_PATTERN = new RegExp(`[\\\\/](${GATED_SPECS.join('|')})\\.spec\\.ts$`);

/**
 * KAN-113 behaviour baseline: Chromium only, gated specs only, against a production build.
 *
 * `next dev` compiles each route on first request. Under parallel workers that pushed page loads and redirects past
 * the test timeouts, so the baseline runs `next build && next start` instead. Run with `npm run test:e2e:baseline`.
 */
/**
 * With the default worker count (10 on the dev machine) the browser and `next start` competed for CPU: tests that need
 * no login hit 30 s timeouts in page.goto, networkidle and even browserContext.newPage (run 4), then passed with 4
 * workers. CI keeps the base config's single worker.
 */
const LOCAL_BASELINE_WORKERS = 4;

export default defineConfig({
  ...baseConfig,
  workers: process.env.CI ? baseConfig.workers : LOCAL_BASELINE_WORKERS,
  projects: (baseConfig.projects ?? [])
    .filter((project) => project.name === 'setup' || project.name === 'chromium')
    .map((project) =>
      project.name === 'chromium' ? { ...project, testMatch: GATED_SPEC_PATTERN } : project
    ),
  webServer: {
    command: 'npm run build && npm run start',
    url: 'http://localhost:3000',
    reuseExistingServer: !process.env.CI,
    timeout: 600_000,
  },
});
