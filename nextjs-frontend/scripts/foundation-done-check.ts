/**
 * Foundation done-check (KAN-113).
 *
 * Foundation is done when the frontend holds no database access or server secrets and the e2e suite passes
 * against FastAPI. This check fails until E6 (KAN-51) removes the last of them; run it with
 * `npm run foundation:check`.
 *
 * File paths are relative to nextjs-frontend/.
 */

export interface SourceFile {
  path: string;
  content: string;
}

export type FindingRule =
  | 'server-secret-env'
  | 'dynamic-env-access'
  | 'prisma-import'
  | 'firebase-admin-import'
  | 'committed-env-file'
  | 'server-only-dependency';

export interface Finding {
  path: string;
  /** 1-based line, or 0 when the finding is about the whole file. */
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

/** The FastAPI base URL; the server-only API client (KAN-33) must read this same variable. */
export const BACKEND_URL_ENV = 'BACKEND_API_URL';

/** Known server-only environment variables: flagged wherever the name appears. */
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

/** Secret-looking names that are allowed: build-time only, never shipped to a server runtime. */
const ALLOWED_SECRET_LOOKING_ENV = new Set(['SENTRY_AUTH_TOKEN']);

const SERVER_ONLY_DEPENDENCIES = /^(prisma|@prisma\/.+|firebase-admin)$/;
const DEPENDENCY_SECTIONS = ['dependencies', 'devDependencies', 'optionalDependencies', 'peerDependencies'];

const KNOWN_SECRET_ENV = new RegExp(
  `(?<![A-Z0-9_])(${SERVER_SECRET_ENV_NAMES.join('|')})(?![A-Z0-9_])`,
  'g'
);
const ENV_READ = /process\.env(?:\.([A-Z0-9_]+)|\[\s*['"`]([A-Z0-9_]+)['"`]\s*\])/g;
const ENV_FILE_KEY = /^\s*(?:export\s+)?([A-Z0-9_]+)\s*=/;
const SECRET_LOOKING_NAME = /(SECRET|PRIVATE_KEY|API_KEY|TOKEN)/;
const DYNAMIC_ENV_READ = /process\.env\[\s*(?!['"`])[^\]]*\]/g;
const MODULE_REFERENCE =
  /(?:\bfrom\s+|\bimport\s+|\brequire\(\s*|\bimport\(\s*|\b(?:vi|jest)\.mock\(\s*)['"]([^'"]+)['"]/g;

const PRISMA_MODULE = /^(prisma|@prisma\/.+|@\/lib\/db|@\/lib\/db\/client)$|(^|\/)db\/client$/;
const FIREBASE_ADMIN_MODULE = /^firebase-admin(\/|$)/;

const ENV_FILE_NAME = /^\.env(\..+)?$/;
const ENV_TEMPLATE_NAME = '.env.example';

/** The check and its tests necessarily name the secrets they look for. */
const IGNORED_PATHS = new Set([
  'scripts/foundation-done-check.ts',
  'scripts/foundation-done-check.cli.ts',
  'src/__tests__/unit/scripts/foundation-done-check.test.ts',
]);

const basename = (path: string): string => path.slice(path.lastIndexOf('/') + 1);

function isSecretLookingEnv(name: string): boolean {
  return (
    SECRET_LOOKING_NAME.test(name) &&
    !name.startsWith('NEXT_PUBLIC_') &&
    !ALLOWED_SECRET_LOOKING_ENV.has(name)
  );
}

function classifyModule(specifier: string): FindingRule | null {
  if (PRISMA_MODULE.test(specifier)) return 'prisma-import';
  if (FIREBASE_ADMIN_MODULE.test(specifier)) return 'firebase-admin-import';
  return null;
}

function envNamesOnLine(text: string, isEnvFile: boolean): string[] {
  const known = [...text.matchAll(KNOWN_SECRET_ENV)].map((m) => m[1]);
  const read = [...text.matchAll(ENV_READ)].map((m) => m[1] ?? m[2]);
  const declared = isEnvFile ? [ENV_FILE_KEY.exec(text)?.[1]].filter((n): n is string => !!n) : [];
  const heuristic = [...read, ...declared].filter(isSecretLookingEnv);
  return [...new Set([...known, ...heuristic])];
}

function scanLine(path: string, text: string, line: number, isEnvFile: boolean): Finding[] {
  const envFindings = envNamesOnLine(text, isEnvFile).map(
    (match): Finding => ({ path, line, rule: 'server-secret-env', match })
  );
  const dynamicFindings = [...text.matchAll(DYNAMIC_ENV_READ)].map(
    (m): Finding => ({ path, line, rule: 'dynamic-env-access', match: m[0] })
  );
  const importFindings = [...text.matchAll(MODULE_REFERENCE)].flatMap((m): Finding[] => {
    const rule = classifyModule(m[1]);
    return rule ? [{ path, line, rule, match: m[1] }] : [];
  });
  return [...envFindings, ...dynamicFindings, ...importFindings];
}

function scanPackageJson(file: SourceFile): Finding[] {
  let manifest: Record<string, unknown>;
  try {
    manifest = JSON.parse(file.content) as Record<string, unknown>;
  } catch {
    return [];
  }
  return DEPENDENCY_SECTIONS.flatMap((section) => Object.keys((manifest[section] ?? {}) as object))
    .filter((name) => SERVER_ONLY_DEPENDENCIES.test(name))
    .map((name): Finding => ({ path: file.path, line: 0, rule: 'server-only-dependency', match: name }));
}

function scanFile(file: SourceFile): Finding[] {
  const name = basename(file.path);
  const isEnvFile = ENV_FILE_NAME.test(name);
  const fileFindings: Finding[] =
    isEnvFile && name !== ENV_TEMPLATE_NAME
      ? [{ path: file.path, line: 0, rule: 'committed-env-file', match: name }]
      : [];
  const dependencyFindings = file.path === 'package.json' ? scanPackageJson(file) : [];
  const lineFindings = file.content
    .split(/\r?\n/)
    .flatMap((text, index) => scanLine(file.path, text, index + 1, isEnvFile));
  return fileFindings.length > 0 ? fileFindings : [...dependencyFindings, ...lineFindings];
}

export function scanForServerSecrets(files: readonly SourceFile[]): Finding[] {
  return files
    .map((file) => ({ ...file, path: file.path.replace(/\\/g, '/') }))
    .filter((file) => !IGNORED_PATHS.has(file.path))
    .flatMap(scanFile);
}

const errorMessage = (error: unknown): string => (error instanceof Error ? error.message : String(error));

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

  try {
    const exitCode = await options.runE2E(backendUrl);
    if (exitCode !== 0) {
      return {
        ok: false,
        findings,
        reason: `e2e suite against FastAPI failed (exit code ${exitCode})`,
      };
    }
  } catch (error: unknown) {
    return { ok: false, findings, reason: `e2e suite against FastAPI crashed: ${errorMessage(error)}` };
  }

  return { ok: true, findings };
}
