/**
 * Environment for e2e runs (KAN-113). CommonJS so playwright.config.ts and the .mjs scripts can both load it.
 *
 * e2e runs against the dedicated Firebase TEST project (storecart-test), never the dev project in .env.local.
 * Precedence, highest first: real environment variables (CI), .env.e2e.local, .env.local, .env.
 * .env.e2e.local holds the test project's public web config, its FIREBASE_ADMIN_* service account and the generated
 * e2e accounts. It is gitignored. Nothing here prints a value; errors name variables only.
 */
/* eslint-disable @typescript-eslint/no-require-imports -- CommonJS script (.cjs) */
const fs = require('node:fs');
const path = require('node:path');
const dotenv = require('dotenv');

const E2E_ENV_FILE = '.env.e2e.local';
/** Separate Next.js output folder for e2e builds, so the developer's normal `.next` build is never replaced. */
const E2E_DIST_DIR = '.next-e2e';
const E2E_BUILD_MARKER = 'e2e-build.json';

const FIREBASE_WEB_VARS = [
  'NEXT_PUBLIC_FIREBASE_API_KEY',
  'NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN',
  'NEXT_PUBLIC_FIREBASE_PROJECT_ID',
  'NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET',
  'NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID',
  'NEXT_PUBLIC_FIREBASE_APP_ID',
];
const FIREBASE_ADMIN_VARS = [
  'FIREBASE_ADMIN_PROJECT_ID',
  'FIREBASE_ADMIN_CLIENT_EMAIL',
  'FIREBASE_ADMIN_PRIVATE_KEY',
];

/** Never taken from env files: Next.js sets NODE_ENV itself, and NODE_ENV=development from .env.local breaks builds. */
const FILE_IGNORED_VARS = new Set(['NODE_ENV']);

function parseEnvFile(cwd, file) {
  const fullPath = path.join(cwd, file);
  const parsed = fs.existsSync(fullPath) ? dotenv.parse(fs.readFileSync(fullPath)) : {};
  return Object.fromEntries(Object.entries(parsed).filter(([name]) => !FILE_IGNORED_VARS.has(name)));
}

function definedOnly(env) {
  return Object.fromEntries(Object.entries(env).filter(([, value]) => value !== undefined));
}

const FIREBASE_VARS = new Set([...FIREBASE_WEB_VARS, ...FIREBASE_ADMIN_VARS]);

/** The developer's files minus every Firebase variable, so the dev project can never leak into e2e. */
function withoutFirebaseVars(env) {
  return Object.fromEntries(Object.entries(env).filter(([name]) => !FIREBASE_VARS.has(name)));
}

/**
 * The merged e2e environment. Variables from .env.e2e.local override .env.local and .env; real environment
 * variables override all files. Firebase variables come only from .env.e2e.local or the real environment, never
 * from .env/.env.local (the dev project). Returns a new object; process.env is not changed.
 */
function loadE2eEnv(cwd = process.cwd()) {
  const devFiles = { ...parseEnvFile(cwd, '.env'), ...parseEnvFile(cwd, '.env.local') };
  // Prisma loads .env into process.env when @prisma/client is imported, so a Firebase value in process.env that
  // equals the dev files' value came from those files, not from a real (CI) environment variable. Drop it.
  const realEnv = Object.fromEntries(
    Object.entries(definedOnly(process.env)).filter(
      ([name, value]) => !FIREBASE_VARS.has(name) || (value !== '' && value !== devFiles[name])
    )
  );
  return {
    ...withoutFirebaseVars(devFiles),
    ...parseEnvFile(cwd, E2E_ENV_FILE),
    ...realEnv,
  };
}

/**
 * Put the e2e env into process.env (for the Playwright runner and workers). Firebase variables the e2e env lacks are
 * set to '' so that nothing loaded later (Prisma loads .env, Next.js loads .env.local) can fill in the dev project.
 */
function applyE2eEnv(cwd = process.cwd()) {
  const env = loadE2eEnv(cwd);
  const blanks = Object.fromEntries([...FIREBASE_VARS].filter((name) => !env[name]).map((name) => [name, '']));
  Object.assign(process.env, env, blanks);
  return env;
}

/**
 * Env for a `next build` / `next start` child process. Next.js fills variables that are not set from .env.local,
 * which would bring in the dev project, so every Firebase variable the e2e env lacks is set to an empty string.
 * Sentry is disabled (its SDK is enabled only when NEXT_PUBLIC_SENTRY_DSN is non-empty), and the output goes to the
 * separate e2e folder.
 */
function toNextProcessEnv(env) {
  const blanks = Object.fromEntries([...FIREBASE_VARS].filter((name) => !env[name]).map((name) => [name, '']));
  return { ...env, ...blanks, NEXT_PUBLIC_SENTRY_DSN: '', NEXT_DIST_DIR: E2E_DIST_DIR };
}

/** Variables from `names` that are unset or empty in `env`. */
function missingVars(env, names) {
  return names.filter((name) => !env[name]);
}

/**
 * Throws a clear error, naming variables only, when the e2e Firebase config is incomplete or points at the dev
 * project. `requireAdmin` also checks the FIREBASE_ADMIN_* service account (needed by the server and account setup).
 */
function assertE2eFirebaseEnv(env, { requireAdmin = true, cwd = process.cwd() } = {}) {
  const required = requireAdmin ? [...FIREBASE_WEB_VARS, ...FIREBASE_ADMIN_VARS] : FIREBASE_WEB_VARS;
  const missing = missingVars(env, required);
  if (missing.length > 0) {
    throw new Error(
      `e2e Firebase config is incomplete. Add these variables to ${E2E_ENV_FILE} (values for the storecart-test ` +
        `project): ${missing.join(', ')}. See docs/developer/testing.md.`
    );
  }

  // The dev project (.env.local) and the test project must never be mixed.
  const devProjectId = parseEnvFile(cwd, '.env.local').NEXT_PUBLIC_FIREBASE_PROJECT_ID;
  if (devProjectId && env.NEXT_PUBLIC_FIREBASE_PROJECT_ID === devProjectId) {
    throw new Error(
      `e2e would use the dev Firebase project from .env.local. Set the storecart-test web config in ${E2E_ENV_FILE}.`
    );
  }

  if (requireAdmin && env.FIREBASE_ADMIN_PROJECT_ID !== env.NEXT_PUBLIC_FIREBASE_PROJECT_ID) {
    throw new Error(
      'FIREBASE_ADMIN_PROJECT_ID and NEXT_PUBLIC_FIREBASE_PROJECT_ID name different Firebase projects. The e2e ' +
        `service account in ${E2E_ENV_FILE} must belong to the same test project as the web config.`
    );
  }
}

module.exports = {
  E2E_ENV_FILE,
  E2E_DIST_DIR,
  E2E_BUILD_MARKER,
  FIREBASE_WEB_VARS,
  FIREBASE_ADMIN_VARS,
  loadE2eEnv,
  applyE2eEnv,
  toNextProcessEnv,
  missingVars,
  assertE2eFirebaseEnv,
};
