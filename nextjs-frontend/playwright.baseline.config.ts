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
  'account-lifecycle',
  'settings-totp',
] as const;

const GATED_SPEC_PATTERN = new RegExp(`[\\\\/](${GATED_SPECS.join('|')})\\.spec\\.ts$`);

/**
 * KAN-113 behaviour baseline: Chromium only, gated specs only, against a production build.
 *
 * `next dev` compiles each route on first request. Under parallel workers that pushed page loads and redirects past
 * the test timeouts, so the baseline serves a production build. It never builds: `npm run test:e2e:build` makes the
 * e2e build once (separate .next-e2e folder, test Firebase project, Sentry off) and scripts/e2e-start.mjs refuses to
 * serve a missing or mismatched build. `npm run test:e2e:baseline:build` does both.
 *
 * A server already running on the e2e port (E2E_PORT, default 3000) is reused only when E2E_REUSE_SERVER=1, so a normal dev server (dev Firebase
 * project) is never tested by accident. Start a reusable one with `node scripts/e2e-start.mjs`.
 */
/**
 * With the default worker count (10 on the dev machine) the browser and `next start` competed for CPU: tests that need
 * no login hit 30 s timeouts in page.goto, networkidle and even browserContext.newPage (run 4), then passed with 4
 * workers. CI keeps the base config's single worker.
 */
const LOCAL_BASELINE_WORKERS = 4;
const SERVER_START_TIMEOUT_MS = 120_000;

export default defineConfig({
  ...baseConfig,
  workers: process.env.CI ? baseConfig.workers : LOCAL_BASELINE_WORKERS,
  projects: (baseConfig.projects ?? [])
    .filter((project) => project.name === 'setup' || project.name === 'chromium')
    .map((project) =>
      project.name === 'chromium' ? { ...project, testMatch: GATED_SPEC_PATTERN } : project
    ),
  webServer: {
    command: 'node scripts/e2e-start.mjs',
    url: process.env.E2E_BASE_URL ?? 'http://localhost:3000',
    reuseExistingServer: !process.env.CI && process.env.E2E_REUSE_SERVER === '1',
    timeout: SERVER_START_TIMEOUT_MS,
  },
});
