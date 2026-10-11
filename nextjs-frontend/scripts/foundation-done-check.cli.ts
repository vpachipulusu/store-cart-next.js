/**
 * CLI for the Foundation done-check (KAN-113): `npm run foundation:check`.
 * Scans every git-tracked file in nextjs-frontend/, then runs the e2e suite against FastAPI at BACKEND_API_URL.
 */
import { execFileSync, spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { BACKEND_URL_ENV, runDoneCheck, type Finding, type SourceFile } from './foundation-done-check';

const HEALTH_TIMEOUT_MS = 5_000;

function trackedFrontendFiles(): SourceFile[] {
  const listing = execFileSync('git', ['ls-files', '-z'], { encoding: 'utf8' });
  return listing
    .split('\0')
    .filter(Boolean)
    .flatMap((path): SourceFile[] => {
      const content = readFileSync(path, 'utf8');
      return content.includes('\0') ? [] : [{ path, content }];
    });
}

async function checkHealth(healthUrl: string): Promise<boolean> {
  try {
    const response = await fetch(healthUrl, { signal: AbortSignal.timeout(HEALTH_TIMEOUT_MS) });
    return response.ok;
  } catch {
    return false;
  }
}

function runE2E(backendUrl: string): Promise<number> {
  return new Promise((resolve) => {
    const child = spawn('npx', ['playwright', 'test', '--project=chromium'], {
      stdio: 'inherit',
      shell: process.platform === 'win32',
      env: { ...process.env, [BACKEND_URL_ENV]: backendUrl },
    });
    child.on('error', () => resolve(1));
    child.on('exit', (code) => resolve(code ?? 1));
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

async function main(): Promise<void> {
  const result = await runDoneCheck({
    files: trackedFrontendFiles(),
    backendUrl: process.env[BACKEND_URL_ENV],
    checkHealth,
    runE2E,
  });

  if (result.ok) {
    process.stdout.write('Foundation done-check passed: no server secrets in the frontend, e2e green against FastAPI.\n');
    return;
  }

  printFindings(result.findings);
  process.stderr.write(`\nFoundation done-check FAILED: ${result.reason}\n`);
  process.exitCode = 1;
}

main().catch((error: unknown) => {
  process.stderr.write(`Foundation done-check crashed: ${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 2;
});
