#!/usr/bin/env node
/**
 * One command for local Playwright E2E (KAN-178): `npm run test:e2e:local -- <spec...> [playwright args]`.
 *
 * Steps (each timed, summary printed at the end):
 *   setup    install deps if missing/stale (npm ci --prefer-offline), prisma generate, Chromium only if absent,
 *            env files copied from the main checkout (or an exact message about what to copy)
 *   build    `next build` into .next-e2e via scripts/e2e-build.mjs, skipped when nothing changed since the last build
 *   serve    `next start` on a free, stable per-checkout port (scripts/e2e-start.mjs), then warm the pages
 *   test     Playwright, chromium + setup projects only, a sane worker count (playwright.local.config.ts)
 *   cleanup  the server process tree is always stopped on exit/Ctrl+C
 *
 * Production build + start is used instead of `next dev`: dev compiles each route on first request (40-58 s for `/`
 * and `/login`), which broke the auth setup and caused hydration timeouts under parallel workers.
 * The developer's own `.next` and dev server are never touched.
 */
import { spawn, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import {
  copyFileSync,
  existsSync,
  lstatSync,
  mkdirSync,
  openSync,
  readFileSync,
  rmSync,
  statSync,
  symlinkSync,
  writeFileSync,
} from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import { performance } from 'node:perf_hooks';
import e2eEnv from './e2e-env.cjs';

const IS_WINDOWS = process.platform === 'win32';
const ENV_FILES = ['.env', '.env.local', '.env.e2e.local'];
const REQUIRED_ENV_FILE = e2eEnv.E2E_ENV_FILE;
const FINGERPRINT_FILE = path.join(e2eEnv.E2E_DIST_DIR, 'local-fingerprint');
const SERVER_LOG = path.join('test-results', 'e2e-local-server.log');
const PORT_RANGE_START = 3100;
const PORT_RANGE_SIZE = 800;
const SERVER_READY_TIMEOUT_MS = 120_000;
const WARM_PATHS = ['/', '/login', '/signup', '/pricing', '/dashboard'];

const timings = [];

function log(message) {
  console.log(`[e2e-local] ${message}`);
}

function die(message) {
  console.error(`[e2e-local] ${message}`);
  process.exit(1);
}

/** Run `fn`, record how long it took under `label`. */
async function timed(label, fn) {
  const start = performance.now();
  try {
    return await fn();
  } finally {
    timings.push([label, (performance.now() - start) / 1000]);
  }
}

function run(command, args, options = {}) {
  return spawnSync(command, args, { stdio: 'inherit', shell: IS_WINDOWS, ...options });
}

function git(args) {
  const result = spawnSync('git', args, { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
  return result.status === 0 ? result.stdout : '';
}

// ---- setup -----------------------------------------------------------------------------------------------------

/** The primary checkout's nextjs-frontend folder, or null when this is the primary checkout. */
function mainFrontendDir() {
  const commonDir = git(['rev-parse', '--path-format=absolute', '--git-common-dir']).trim();
  if (!commonDir) return null;
  const main = path.join(path.dirname(commonDir), 'nextjs-frontend');
  return path.resolve(main) === path.resolve(process.cwd()) ? null : main;
}

function ensureEnvFiles() {
  const mainDir = mainFrontendDir();
  for (const file of ENV_FILES) {
    if (existsSync(file)) continue;
    const source = mainDir && path.join(mainDir, file);
    if (source && existsSync(source)) {
      copyFileSync(source, file);
      log(`copied ${file} from the main checkout`);
    }
  }
  if (!existsSync(REQUIRED_ENV_FILE)) {
    die(
      `${REQUIRED_ENV_FILE} is missing and was not found in the main checkout either.\n` +
        `Create nextjs-frontend/${REQUIRED_ENV_FILE} with the storecart-test Firebase web config, FIREBASE_ADMIN_*, ` +
        `DATABASE_URL (test database) and the e2e accounts (see docs/developer/testing.md), or copy it from a ` +
        `colleague's checkout. Optional: .env and .env.local (copied automatically when present).`
    );
  }
}

const mtime = (file) => (existsSync(file) ? statSync(file).mtimeMs : 0);

const sameFile = (a, b) =>
  existsSync(a) && existsSync(b) && readFileSync(a).equals(readFileSync(b));

/**
 * Link this checkout's node_modules to the primary checkout's (a junction on Windows) when package-lock.json and the
 * Prisma schema are byte-identical, which saves the ~4 minute `npm ci`. Opt out with E2E_LOCAL_NO_LINK=1.
 * Never links over an existing node_modules folder.
 */
function canShareMainModules(mainDir) {
  return (
    Boolean(mainDir) &&
    process.env.E2E_LOCAL_NO_LINK !== '1' &&
    existsSync(path.join(mainDir, 'node_modules', '.package-lock.json')) &&
    sameFile('package-lock.json', path.join(mainDir, 'package-lock.json')) &&
    sameFile(path.join('prisma', 'schema.prisma'), path.join(mainDir, 'prisma', 'schema.prisma'))
  );
}

const isLinkedModules = () =>
  existsSync('node_modules') && lstatSync('node_modules').isSymbolicLink();

function ensureDependencies() {
  const mainDir = mainFrontendDir();
  if (isLinkedModules()) {
    if (canShareMainModules(mainDir)) return;
    // Lockfile drifted from the primary checkout: drop only the link (never `npm ci` through it) and install here.
    log('the primary checkout no longer matches package-lock.json; removing the node_modules link');
    rmSync('node_modules', { recursive: false, force: true });
  } else if (!existsSync('node_modules') && canShareMainModules(mainDir)) {
    symlinkSync(path.resolve(mainDir, 'node_modules'), 'node_modules', 'junction');
    log('linked node_modules to the primary checkout (identical package-lock.json)');
    return;
  }
  const installed = path.join('node_modules', '.package-lock.json');
  if (mtime(installed) > 0 && mtime(installed) >= mtime('package-lock.json')) return;
  log('installing dependencies (npm ci --prefer-offline)');
  const result = run('npm', ['ci', '--prefer-offline', '--no-audit', '--no-fund']);
  if (result.status !== 0) die('npm ci failed.');
}

function ensurePrismaClient() {
  const generated = path.join('node_modules', '.prisma', 'client', 'index.js');
  if (mtime(generated) > 0 && mtime(generated) >= mtime(path.join('prisma', 'schema.prisma')))
    return;
  log('generating the Prisma client');
  if (run('npm', ['run', 'db:generate']).status !== 0) die('prisma generate failed.');
}

async function ensureChromium() {
  const { chromium } = await import('@playwright/test');
  if (existsSync(chromium.executablePath())) return;
  log('installing the Chromium browser for Playwright (one-off, cached globally)');
  if (run('npx', ['playwright', 'install', 'chromium']).status !== 0)
    die('playwright install failed.');
}

// ---- port ------------------------------------------------------------------------------------------------------

function isPortFree(port) {
  return new Promise((resolve) => {
    const probe = net.createServer();
    probe.once('error', () => resolve(false));
    probe.listen(port, () => probe.close(() => resolve(true)));
  });
}

/**
 * E2E_PORT if set, else a port derived from this checkout's path, so every worktree gets its own stable port (the build
 * bakes the port in, so a stable port keeps the build reusable). Walks forward when the port is taken.
 */
async function pickPort() {
  if (process.env.E2E_PORT) {
    const port = Number(process.env.E2E_PORT);
    if (!(await isPortFree(port))) {
      die(
        `E2E_PORT=${port} is already in use. Unset it to let the script pick a free port, or stop what uses it.`
      );
    }
    return port;
  }
  const hash = createHash('sha1').update(process.cwd()).digest().readUInt16BE(0);
  for (let offset = 0; offset < PORT_RANGE_SIZE; offset += 1) {
    const port = PORT_RANGE_START + ((hash + offset) % PORT_RANGE_SIZE);
    if (await isPortFree(port)) return port;
  }
  return die('No free port found in the 3100-3899 range.');
}

// ---- build -----------------------------------------------------------------------------------------------------

/** Changes with the committed tree (not the commit id), uncommitted edits (tracked or untracked) and the port, which is baked into the build. */
function sourceFingerprint(port) {
  const hash = createHash('sha1');
  hash.update(`${git(['rev-parse', 'HEAD'])}\n${port}\n${git(['diff', 'HEAD'])}`);
  for (const file of git(['ls-files', '-o', '--exclude-standard', '-z'])
    .split('\0')
    .filter(Boolean)) {
    hash.update(file);
    try {
      hash.update(readFileSync(file));
    } catch {
      // Deleted between listing and reading: the next run sees the new state.
    }
  }
  hash.update(readFileSync(REQUIRED_ENV_FILE));
  return hash.digest('hex');
}

function ensureBuild(port, serverEnv) {
  const fingerprint = sourceFingerprint(port);
  const hasBuild = existsSync(path.join(e2eEnv.E2E_DIST_DIR, 'BUILD_ID'));
  if (
    hasBuild &&
    existsSync(FINGERPRINT_FILE) &&
    readFileSync(FINGERPRINT_FILE, 'utf8') === fingerprint
  ) {
    log('e2e build is up to date, skipping `next build`');
    return;
  }
  log('building the app for e2e (production build into .next-e2e)');
  if (run('node', ['scripts/e2e-build.mjs'], { env: serverEnv }).status !== 0)
    die('e2e build failed.');
  writeFileSync(FINGERPRINT_FILE, fingerprint);
}

// ---- server ----------------------------------------------------------------------------------------------------

let server = null;

function stopServer() {
  if (!server || server.exitCode !== null || server.pid === undefined) return;
  if (IS_WINDOWS) {
    spawnSync('taskkill', ['/pid', String(server.pid), '/T', '/F'], { stdio: 'ignore' });
  } else {
    try {
      process.kill(-server.pid, 'SIGTERM');
    } catch {
      server.kill('SIGTERM');
    }
  }
}

function startServer(serverEnv) {
  mkdirSync(path.dirname(SERVER_LOG), { recursive: true });
  const logFd = openSync(SERVER_LOG, 'w');
  server = spawn('node', ['scripts/e2e-start.mjs'], {
    env: serverEnv,
    stdio: ['ignore', logFd, logFd],
    detached: !IS_WINDOWS,
  });
  server.on('exit', (code) => {
    if (code) log(`server exited with code ${code}; see ${SERVER_LOG}`);
  });
}

function tail(file, lines = 15) {
  return readFileSync(file, 'utf8').trimEnd().split('\n').slice(-lines).join('\n');
}

async function waitForServer(baseUrl) {
  const deadline = Date.now() + SERVER_READY_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (server.exitCode !== null) {
      die(`The e2e server exited before it was ready. Last log lines:\n${tail(SERVER_LOG)}`);
    }
    try {
      await fetch(baseUrl, { redirect: 'manual' });
      return;
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
  }
  die(
    `The e2e server did not answer on ${baseUrl} within ${SERVER_READY_TIMEOUT_MS / 1000}s. See ${SERVER_LOG}.`
  );
}

/** Request each page the specs hit once, so the first Playwright request is not the slow one. */
async function warmPages(baseUrl) {
  await Promise.all(
    WARM_PATHS.map((route) =>
      fetch(`${baseUrl}${route}`, { redirect: 'follow' }).catch(() => undefined)
    )
  );
}

// ---- main ------------------------------------------------------------------------------------------------------

function printSummary() {
  const total = timings.reduce((sum, [, secs]) => sum + secs, 0);
  console.log('\n[e2e-local] timings');
  for (const [label, secs] of timings)
    console.log(`  ${label.padEnd(10)} ${secs.toFixed(1).padStart(7)} s`);
  console.log(`  ${'total'.padEnd(10)} ${total.toFixed(1).padStart(7)} s`);
}

async function main() {
  const args = process.argv.slice(2);
  if (args.includes('--help') || args.includes('-h')) {
    console.log(
      'Usage: npm run test:e2e:local -- [spec files or Playwright args]\nSee docs/developer/local-e2e.md.'
    );
    return 0;
  }

  await timed('setup', async () => {
    ensureEnvFiles();
    ensureDependencies();
    ensurePrismaClient();
    await ensureChromium();
  });

  const port = await pickPort();
  const baseUrl = `http://localhost:${port}`;
  log(`using ${baseUrl}`);
  const serverEnv = { ...process.env, E2E_PORT: String(port), E2E_BASE_URL: baseUrl };

  await timed('build', async () => ensureBuild(port, serverEnv));
  await timed('serve+warm', async () => {
    startServer(serverEnv);
    await waitForServer(baseUrl);
    await warmPages(baseUrl);
  });

  let status = 1;
  await timed('test', async () => {
    const result = run(
      'npx',
      ['playwright', 'test', '--config=playwright.local.config.ts', ...args],
      {
        env: serverEnv,
      }
    );
    status = result.status ?? 1;
  });
  return status;
}

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    stopServer();
    process.exit(130);
  });
}
process.on('exit', stopServer);

main()
  .then((status) => {
    printSummary();
    process.exit(status);
  })
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });
