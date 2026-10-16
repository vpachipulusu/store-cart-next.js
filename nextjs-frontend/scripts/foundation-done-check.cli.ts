/**
 * CLI for the Foundation done-check (KAN-113): `npm run foundation:check`.
 * Scans every git-tracked file in nextjs-frontend/, then runs the e2e suite against FastAPI at BACKEND_API_URL.
 * `--scan-only` (`npm run foundation:scan`) stops after the scan; CI runs that (KAN-208).
 */
import { execFileSync, spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  BACKEND_URL_ENV,
  runDoneCheck,
  scanForServerSecrets,
  type Finding,
  type SourceFile,
} from './foundation-done-check';

const HEALTH_TIMEOUT_MS = 5_000;
const BINARY_SNIFF_BYTES = 8_000;
/** nextjs-frontend/, wherever the command is run from. */
const FRONTEND_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');

function readTextFile(path: string): string | null {
  try {
    const bytes = readFileSync(join(FRONTEND_ROOT, path));
    return bytes.subarray(0, BINARY_SNIFF_BYTES).includes(0) ? null : bytes.toString('utf8');
  } catch {
    return null; // listed by git but deleted or unreadable in the working tree
  }
}

/** Tracked files plus untracked, non-ignored ones, so a new file is checked before it is committed. */
function frontendFiles(): SourceFile[] {
  const listing = execFileSync(
    'git',
    ['ls-files', '-z', '--cached', '--others', '--exclude-standard'],
    {
      cwd: FRONTEND_ROOT,
      encoding: 'utf8',
      maxBuffer: 64 * 1024 * 1024,
    }
  );
  return [...new Set(listing.split('\0').filter(Boolean))].flatMap((path): SourceFile[] => {
    const content = readTextFile(path);
    return content === null ? [] : [{ path, content }];
  });
}

async function checkHealth(healthUrl: string): Promise<boolean> {
  try {
    const response = await fetch(healthUrl, { signal: AbortSignal.timeout(HEALTH_TIMEOUT_MS) });
    if (!response.ok) process.stderr.write(`Health check returned HTTP ${response.status}\n`);
    return response.ok;
  } catch (error: unknown) {
    process.stderr.write(
      `Health check failed: ${error instanceof Error ? error.message : String(error)}\n`
    );
    return false;
  }
}

/**
 * Runs Playwright with BACKEND_API_URL set. CI=1 makes Playwright start a fresh dev server (which inherits the
 * variable) instead of reusing one already running on :3000 that may not point at FastAPI.
 */
function runE2E(backendUrl: string): Promise<number> {
  return new Promise((resolvePromise, reject) => {
    const child = spawn('npx', ['playwright', 'test', '--project=chromium', '--reporter=list'], {
      cwd: FRONTEND_ROOT,
      stdio: 'inherit',
      shell: process.platform === 'win32',
      env: { ...process.env, CI: '1', [BACKEND_URL_ENV]: backendUrl },
    });
    child.on('error', reject);
    child.on('close', (code) => resolvePromise(code ?? 1));
  });
}

function printFindings(findings: readonly Finding[]): void {
  const rules = [...new Set(findings.map((f) => f.rule))];
  for (const rule of rules) {
    const items = findings.filter((f) => f.rule === rule);
    process.stderr.write(`\n${rule} (${items.length})\n`);
    for (const f of items) process.stderr.write(`  ${f.path}:${f.line}  ${f.match}\n`);
  }
}

function scanOnly(): boolean {
  const findings = scanForServerSecrets(frontendFiles());
  if (findings.length === 0) {
    process.stdout.write('Foundation scan passed: no server secrets or backend SDKs in the frontend.\n');
    return true;
  }
  printFindings(findings);
  process.stderr.write(
    `\nFoundation scan FAILED: ${findings.length} reference(s) to database access or server secrets remain in the frontend\n`
  );
  return false;
}

async function main(): Promise<void> {
  if (process.argv.includes('--scan-only')) {
    if (!scanOnly()) process.exitCode = 1;
    return;
  }
  const result = await runDoneCheck({
    files: frontendFiles(),
    backendUrl: process.env[BACKEND_URL_ENV],
    checkHealth,
    runE2E,
  });

  if (result.ok) {
    process.stdout.write(
      'Foundation done-check passed: no server secrets in the frontend, e2e green against FastAPI.\n'
    );
    return;
  }

  printFindings(result.findings);
  process.stderr.write(`\nFoundation done-check FAILED: ${result.reason}\n`);
  process.exitCode = 1;
}

main().catch((error: unknown) => {
  process.stderr.write(
    `Foundation done-check crashed: ${error instanceof Error ? error.message : String(error)}\n`
  );
  process.exitCode = 2;
});
