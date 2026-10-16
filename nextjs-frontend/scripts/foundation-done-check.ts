/**
 * Foundation done-check (KAN-113).
 *
 * Foundation is done when the frontend holds no database access or server secrets and the e2e suite passes
 * against FastAPI. `npm run foundation:check` does both; `npm run foundation:scan` is the scan alone, which the
 * frontend CI job runs (KAN-208) so a server secret, a Prisma, Stripe or firebase-admin import, or a server-only
 * dependency can never come back.
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
  | 'stripe-import'
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

const SERVER_ONLY_DEPENDENCIES = /^(prisma|@prisma\/.+|firebase-admin|stripe)$/;
const DEPENDENCY_SECTIONS = [
  'dependencies',
  'devDependencies',
  'optionalDependencies',
  'peerDependencies',
];

const KNOWN_SECRET_ENV = new RegExp(
  `(?<![A-Z0-9_])(${SERVER_SECRET_ENV_NAMES.join('|')})(?![A-Z0-9_])`,
  'g'
);
const ENV_READ = /process\.env(?:\.([A-Z0-9_]+)|\[\s*['"`]([A-Z0-9_]+)['"`]\s*\])/g;
const ENV_FILE_KEY = /^\s*(?:export\s+)?([A-Z0-9_]+)\s*=/;
const SECRET_LOOKING_NAME = /(SECRET|PRIVATE_KEY|API_KEY|TOKEN)/;
/** `const { A, B: alias, C = 1 } = process.env`, possibly over several lines. */
const ENV_DESTRUCTURING = /\b(?:const|let|var)\s*\{([^}]*)\}\s*(?::[^=]+)?=\s*process\.env\b/g;
const DYNAMIC_ENV_READ = /process\.env\[\s*(?!['"`])[^\]]*\]/g;
const MODULE_REFERENCE =
  /(?:\bfrom\s+|\bimport\s+|\brequire\(\s*|\bimport\(\s*|\b(?:vi|jest)\.mock\(\s*)['"]([^'"]+)['"]/g;

const PRISMA_MODULE = /^(prisma|@prisma\/.+|@\/lib\/db|@\/lib\/db\/client)$|(^|\/)db\/client$/;
// Includes the removed wrapper modules, so a re-created one is flagged too. `@stripe/stripe-js` is client-safe.
const FIREBASE_ADMIN_MODULE = /^(firebase-admin(\/|$)|@\/lib\/firebase\/admin$)/;
const STRIPE_MODULE = /^(stripe(\/|$)|@\/lib\/stripe\/server$)/;

const ENV_FILE_NAME = /^\.env(\..+)?$/;
const ENV_TEMPLATE_NAME = '.env.example';

/** The check and its tests necessarily name the secrets they look for. */
const IGNORED_PATHS = new Set([
  'scripts/foundation-done-check.ts',
  'scripts/foundation-done-check.cli.ts',
  'src/__tests__/unit/scripts/foundation-done-check.test.ts',
  'src/__tests__/unit/config/eslint-restricted-imports.test.ts',
]);

/**
 * Files where a named server secret is expected, so the name itself is not a finding:
 * - the e2e account tooling reads the e2e Firebase service account (FIREBASE_ADMIN_*) to create and delete test
 *   users in the dedicated TEST project (KAN-113, KAN-208). It runs only on a developer machine or in the e2e job,
 *   never in the deployed frontend.
 * - `.env.example` is the template the coordinator owns; it still lists the retired server variables and is
 *   cleaned up outside the developer branches. Remove this entry once it is clean.
 */
const E2E_TOOLING_PATHS = new Set([
  'scripts/e2e-accounts.mjs',
  'scripts/e2e-env.cjs',
  'scripts/firebase-rest-admin.mjs',
  'scripts/setup-e2e-accounts.mjs',
]);
const E2E_TOOLING_ALLOWED_ENV = /^FIREBASE_ADMIN_(PROJECT_ID|CLIENT_EMAIL|PRIVATE_KEY)$/;
const PENDING_TEMPLATE_CLEANUP = new Set(['.env.example']);

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
  if (STRIPE_MODULE.test(specifier)) return 'stripe-import';
  return null;
}

function envNamesOnLine(text: string, isEnvFile: boolean): string[] {
  const known = [...text.matchAll(KNOWN_SECRET_ENV)].map((m) => m[1]);
  const read = [...text.matchAll(ENV_READ)].map((m) => m[1] ?? m[2]);
  const declared = isEnvFile ? [ENV_FILE_KEY.exec(text)?.[1]].filter((n): n is string => !!n) : [];
  const heuristic = [...read, ...declared].filter(isSecretLookingEnv);
  return [...new Set([...known, ...heuristic])];
}

function destructuredNames(pattern: string): string[] {
  return pattern
    .split(',')
    .map((part) => part.trim().split(/[:=\s]/)[0])
    .filter((name) => /^[A-Za-z_$][\w$]*$/.test(name));
}

/** Destructured reads (`const { SECRET } = process.env`) never match the dotted or bracketed read forms. */
function scanEnvDestructuring(path: string, content: string): Finding[] {
  return [...content.matchAll(ENV_DESTRUCTURING)].flatMap((m) =>
    destructuredNames(m[1])
      .filter((name) => isSecretLookingEnv(name) || isKnownSecretEnv(name))
      .map((name): Finding => {
        const nameOffset = (m.index ?? 0) + m[0].indexOf(name);
        const line = content.slice(0, nameOffset).split('\n').length;
        return { path, line, rule: 'server-secret-env', match: name };
      })
  );
}

function isKnownSecretEnv(name: string): boolean {
  return SERVER_SECRET_ENV_NAMES.includes(name);
}

function scanLine(path: string, text: string, line: number, isEnvFile: boolean): Finding[] {
  const envFindings = envNamesOnLine(text, isEnvFile)
    .filter((name) => !(E2E_TOOLING_PATHS.has(path) && E2E_TOOLING_ALLOWED_ENV.test(name)))
    .map(
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
    .map(
      (name): Finding => ({ path: file.path, line: 0, rule: 'server-only-dependency', match: name })
    );
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
  if (fileFindings.length > 0) return fileFindings;
  const seen = new Set(lineFindings.map((f) => `${f.line}:${f.rule}:${f.match}`));
  const destructuringFindings = scanEnvDestructuring(file.path, file.content).filter(
    (f) =>
      !seen.has(`${f.line}:${f.rule}:${f.match}`) &&
      !(E2E_TOOLING_PATHS.has(f.path) && E2E_TOOLING_ALLOWED_ENV.test(f.match))
  );
  return [...dependencyFindings, ...lineFindings, ...destructuringFindings];
}

export function scanForServerSecrets(files: readonly SourceFile[]): Finding[] {
  return files
    .map((file) => ({ ...file, path: file.path.replace(/\\/g, '/') }))
    .filter((file) => !IGNORED_PATHS.has(file.path) && !PENDING_TEMPLATE_CLEANUP.has(file.path))
    .flatMap(scanFile);
}

const errorMessage = (error: unknown): string =>
  error instanceof Error ? error.message : String(error);

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
    return {
      ok: false,
      findings,
      reason: `e2e suite against FastAPI crashed: ${errorMessage(error)}`,
    };
  }

  return { ok: true, findings };
}
