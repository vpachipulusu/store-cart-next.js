#!/usr/bin/env node
/**
 * Serve the e2e build (KAN-113). Playwright's webServer runs this; it never builds.
 *
 * Refuses to start, with a clear message, when:
 * - there is no e2e build in .next-e2e (run `npm run test:e2e:build` first), or
 * - the build was made for a different Firebase project than the current e2e env, or with Sentry on, or
 * - the e2e Firebase config (web config + FIREBASE_ADMIN_* service account) is incomplete.
 * Warns when the build is from a different commit than HEAD.
 */
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import e2eEnv from './e2e-env.cjs';

const { E2E_DIST_DIR, E2E_BUILD_MARKER, loadE2eEnv, toNextProcessEnv, assertE2eFirebaseEnv } = e2eEnv;

function fail(message) {
  console.error(`[e2e-start] ${message}`);
  process.exit(1);
}

function readMarker() {
  const markerPath = path.join(E2E_DIST_DIR, E2E_BUILD_MARKER);
  if (!existsSync(path.join(E2E_DIST_DIR, 'BUILD_ID')) || !existsSync(markerPath)) {
    fail(`No e2e build in ${E2E_DIST_DIR}. Run \`npm run test:e2e:build\` (or \`npm run test:e2e:baseline:build\`).`);
  }
  try {
    return JSON.parse(readFileSync(markerPath, 'utf8'));
  } catch {
    return fail(`${markerPath} is unreadable. Rebuild with \`npm run test:e2e:build\`.`);
  }
}

const env = loadE2eEnv();
try {
  assertE2eFirebaseEnv(env, { requireAdmin: true });
} catch (error) {
  fail(error.message);
}

const marker = readMarker();
if (marker.firebaseProjectId !== env.NEXT_PUBLIC_FIREBASE_PROJECT_ID) {
  fail(
    `The e2e build is for Firebase project "${marker.firebaseProjectId}" but the e2e env uses ` +
      `"${env.NEXT_PUBLIC_FIREBASE_PROJECT_ID}". Rebuild with \`npm run test:e2e:build\`.`
  );
}
if (marker.sentryDisabled !== true) {
  fail('The e2e build was made with Sentry enabled. Rebuild with `npm run test:e2e:build`.');
}

const head = spawnSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' });
if (head.status === 0 && marker.commit !== head.stdout.trim()) {
  console.warn(
    `[e2e-start] Warning: the e2e build is from commit ${marker.commit}, HEAD is ${head.stdout.trim()}. ` +
      'Run `npm run test:e2e:build` to test the current code.'
  );
}

const server = spawn('npx', ['next', 'start'], {
  stdio: 'inherit',
  env: toNextProcessEnv(env),
  shell: process.platform === 'win32',
});
server.on('exit', (code) => process.exit(code ?? 1));
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => server.kill(signal));
}
