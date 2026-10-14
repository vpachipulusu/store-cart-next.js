import os from 'node:os';
import { defineConfig } from '@playwright/test';
import baseConfig from './playwright.config';

/**
 * Local E2E (KAN-178), used by `npm run test:e2e:local` (scripts/e2e-local.mjs).
 *
 * The script owns the server lifecycle (free port, production build, warm-up, cleanup), so this config has no
 * webServer. It runs chromium (plus the auth setup project it depends on) only; CI keeps using playwright.config.ts.
 */
const MAX_LOCAL_WORKERS = 4;
const CPUS_PER_WORKER = 2;

// Beyond ~4 workers the browser and `next start` compete for CPU and tests time out in page.goto (KAN-113 run 4).
const workers = Math.max(
  1,
  Math.min(MAX_LOCAL_WORKERS, Math.floor(os.cpus().length / CPUS_PER_WORKER))
);

export default defineConfig({
  ...baseConfig,
  workers,
  reporter: [['list']],
  projects: (baseConfig.projects ?? []).filter(
    (project) => project.name === 'setup' || project.name === 'chromium'
  ),
  webServer: undefined,
});
