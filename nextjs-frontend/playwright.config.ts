import { defineConfig, devices } from '@playwright/test';
import e2eEnv from './scripts/e2e-env.cjs';
import ports from './scripts/ports.cjs';

// e2e uses the Firebase TEST project from .env.e2e.local (plus the e2e accounts written by `npm run test:setup`),
// never the dev project in .env.local. Real env vars take precedence. See scripts/e2e-env.cjs.
const testEnv = e2eEnv.applyE2eEnv();

// KAN-167: E2E_PORT (default 3000) moves the Playwright server so two checkouts can run in parallel. Tests and
// helpers read the origin from E2E_BASE_URL.
const E2E_PORT = ports.getE2ePort(process.env);
const baseURL = ports.getE2eBaseUrl(process.env);
process.env.E2E_BASE_URL = baseURL;

export default defineConfig({
  testDir: './src/__tests__/e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [['html'], ['list']],
  timeout: 30_000,
  expect: {
    timeout: 10_000,
  },
  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },

  projects: [
    // Setup project for auth state
    {
      name: 'setup',
      testMatch: /.*\.setup\.ts/,
      // The first login can wait on a cold `next dev` compile of /login and /dashboard (KAN-178).
      timeout: 90_000,
    },

    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
      },
      dependencies: ['setup'],
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
      dependencies: ['setup'],
    },
    {
      name: 'webkit',
      use: { ...devices['Desktop Safari'] },
      dependencies: ['setup'],
    },

    // Mobile viewports
    {
      name: 'mobile-chrome',
      use: { ...devices['Pixel 5'] },
      dependencies: ['setup'],
    },
    {
      name: 'mobile-safari',
      use: { ...devices['iPhone 13'] },
      dependencies: ['setup'],
    },
  ],

  webServer: {
    command: `npm run dev -- -p ${E2E_PORT}`,
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    // The dev server gets the e2e env (test Firebase project, Sentry off) and its own output folder.
    env: { ...e2eEnv.toNextProcessEnv(testEnv), NEXT_DIST_DIR: '.next-e2e-dev' },
  },
});
