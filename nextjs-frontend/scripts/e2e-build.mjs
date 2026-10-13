#!/usr/bin/env node
/**
 * Production build for e2e (KAN-113). Run with `npm run test:e2e:build`.
 *
 * - Uses the e2e env (scripts/e2e-env.cjs): the storecart-test Firebase project, never the dev project in .env.local.
 *   NEXT_PUBLIC_* values are baked in at build time, so the e2e build must be separate from the normal build.
 * - Writes to .next-e2e (not .next) and disables Sentry (empty NEXT_PUBLIC_SENTRY_DSN).
 * - Writes a marker with the Firebase project id; scripts/e2e-start.mjs refuses to serve a build whose marker does
 *   not match the current e2e env.
 */
import { spawnSync } from 'node:child_process';
import { rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import e2eEnv from './e2e-env.cjs';

const { E2E_DIST_DIR, E2E_BUILD_MARKER, loadE2eEnv, toNextProcessEnv, assertE2eFirebaseEnv } =
  e2eEnv;

function gitHead() {
  const result = spawnSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' });
  return result.status === 0 ? result.stdout.trim() : 'unknown';
}

const env = loadE2eEnv();
try {
  // The build needs only the public web config; the server checks the admin service account when it starts.
  assertE2eFirebaseEnv(env, { requireAdmin: false });
} catch (error) {
  console.error(error.message);
  process.exit(1);
}

// Start clean: stale generated types from deleted routes would fail the type check. This is our own output folder.
rmSync(E2E_DIST_DIR, { recursive: true, force: true });

const result = spawnSync('npx', ['next', 'build', '--webpack'], {
  stdio: 'inherit',
  env: toNextProcessEnv(env),
  shell: process.platform === 'win32',
});
if (result.status !== 0) {
  process.exit(result.status ?? 1);
}

const marker = {
  firebaseProjectId: env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
  sentryDisabled: true,
  commit: gitHead(),
  builtAt: new Date().toISOString(),
};
writeFileSync(path.join(E2E_DIST_DIR, E2E_BUILD_MARKER), `${JSON.stringify(marker, null, 2)}\n`);
console.log(
  `e2e build ready in ${E2E_DIST_DIR} (Firebase project ${marker.firebaseProjectId}, Sentry off).`
);
