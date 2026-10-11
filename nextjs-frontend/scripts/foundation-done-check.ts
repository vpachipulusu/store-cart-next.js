/**
 * Foundation done-check (KAN-113).
 *
 * Foundation is done when the frontend holds no database access or server secrets and the e2e suite passes
 * against FastAPI. This check fails until E6 (KAN-51) removes the last of them; run it with
 * `npm run foundation:check`.
 */

export interface SourceFile {
  path: string;
  content: string;
}

export type FindingRule = 'server-secret-env' | 'prisma-import' | 'firebase-admin-import';

export interface Finding {
  path: string;
  line: number;
  rule: FindingRule;
  match: string;
}

export type DoneCheckResult =
  | { ok: true; findings: Finding[] }
  | { ok: false; findings: Finding[]; reason: string };

export interface DoneCheckOptions {
  files: SourceFile[];
  backendUrl: string | undefined;
  checkHealth: (healthUrl: string) => Promise<boolean>;
  runE2E: (backendUrl: string) => Promise<number>;
}

export const BACKEND_URL_ENV = 'BACKEND_API_URL';

/** Server-only environment variables that must not appear anywhere in the frontend. */
const SERVER_SECRET_ENV_NAMES = [
  'DATABASE_URL',
  'FIREBASE_ADMIN_PRIVATE_KEY',
  'FIREBASE_ADMIN_CLIENT_EMAIL',
  'FIREBASE_ADMIN_PROJECT_ID',
  'FIREBASE_PRIVATE_KEY',
  'FIREBASE_CLIENT_EMAIL',
  'STRIPE_SECRET_KEY',
  'STRIPE_WEBHOOK_SECRET',
  'RESEND_API_KEY',
  'NEXTAUTH_SECRET',
];

const SERVER_SECRET_ENV = new RegExp(`(?<![A-Z0-9_])(${SERVER_SECRET_ENV_NAMES.join('|')})(?![A-Z0-9_])`, 'g');
const MODULE_REFERENCE = /(?:\bfrom\s+|\brequire\(\s*|\bimport\(\s*)['"]([^'"]+)['"]/g;

const PRISMA_MODULES = new Set(['@prisma/client', '@/lib/db/client']);
const FIREBASE_ADMIN_MODULE = /^firebase-admin(\/|$)/;

/** The check and its tests necessarily name the secrets they look for. */
const IGNORED_PATH = /(^|\/)(scripts\/foundation-done-check[^/]*|foundation-done-check\.test\.ts)$/;

function classifyModule(specifier: string): FindingRule | null {
  if (PRISMA_MODULES.has(specifier)) return 'prisma-import';
  if (FIREBASE_ADMIN_MODULE.test(specifier)) return 'firebase-admin-import';
  return null;
}

function scanLine(path: string, text: string, line: number): Finding[] {
  const envFindings = [...text.matchAll(SERVER_SECRET_ENV)].map(
    (m): Finding => ({ path, line, rule: 'server-secret-env', match: m[1] }),
  );
  const importFindings = [...text.matchAll(MODULE_REFERENCE)].flatMap((m): Finding[] => {
    const rule = classifyModule(m[1]);
    return rule ? [{ path, line, rule, match: m[1] }] : [];
  });
  return [...envFindings, ...importFindings];
}

export function scanForServerSecrets(files: readonly SourceFile[]): Finding[] {
  return files
    .filter((file) => !IGNORED_PATH.test(file.path.replace(/\\/g, '/')))
    .flatMap((file) => file.content.split(/\r?\n/).flatMap((text, index) => scanLine(file.path, text, index + 1)));
}

export async function runDoneCheck(options: DoneCheckOptions): Promise<DoneCheckResult> {
  const findings = scanForServerSecrets(options.files);
  if (findings.length > 0) {
    return {
      ok: false,
      findings,
      reason: `${findings.length} reference(s) to database access or server secrets remain in the frontend`,
    };
  }

  if (!options.backendUrl) {
    return {
      ok: false,
      findings,
      reason: `${BACKEND_URL_ENV} is not set; the e2e suite must run against FastAPI`,
    };
  }

  const backendUrl = options.backendUrl.replace(/\/+$/, '');
  const healthUrl = `${backendUrl}/health`;
  if (!(await options.checkHealth(healthUrl))) {
    return { ok: false, findings, reason: `FastAPI is not healthy at ${healthUrl}` };
  }

  const exitCode = await options.runE2E(backendUrl);
  if (exitCode !== 0) {
    return { ok: false, findings, reason: `e2e suite against FastAPI failed (exit code ${exitCode})` };
  }

  return { ok: true, findings };
}
