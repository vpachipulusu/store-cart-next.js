#!/usr/bin/env node
/**
 * Apply the Prisma schema to the dedicated e2e database (KAN-113). Run with `npm run test:e2e:db`.
 *
 * Uses the e2e env only (scripts/e2e-env.cjs): DATABASE_URL comes from .env.e2e.local (or the real environment in
 * CI), never from .env.local / .env. Refuses to run when DATABASE_URL is missing or equals the dev database. Prints
 * the database host only, never the URL. The repo has no migrations, so this runs `prisma db push`.
 */
import { spawnSync } from 'node:child_process';
import e2eEnv from './e2e-env.cjs';

const { loadE2eEnv, toNextProcessEnv, assertE2eDatabaseEnv } = e2eEnv;

const env = loadE2eEnv();
let fingerprint;
try {
  fingerprint = assertE2eDatabaseEnv(env);
} catch (error) {
  console.error(`[e2e-db] ${error.message}`);
  process.exit(1);
}

console.log(`[e2e-db] Applying the Prisma schema to the e2e database at ${fingerprint}.`);
const result = spawnSync('npx', ['prisma', 'db', 'push', '--skip-generate'], {
  stdio: 'inherit',
  env: toNextProcessEnv(env),
  shell: process.platform === 'win32',
});
process.exit(result.status ?? 1);
