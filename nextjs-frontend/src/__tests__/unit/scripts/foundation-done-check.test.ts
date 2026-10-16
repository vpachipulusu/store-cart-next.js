import { describe, expect, it, vi } from 'vitest';
import {
  scanForServerSecrets,
  runDoneCheck,
  type SourceFile,
} from '../../../../scripts/foundation-done-check';

const file = (path: string, content: string): SourceFile => ({ path, content });

describe('scanForServerSecrets', () => {
  it('returns no findings for client-safe code', () => {
    const findings = scanForServerSecrets([
      file('src/app/page.tsx', 'const key = process.env.NEXT_PUBLIC_FIREBASE_API_KEY;'),
    ]);

    expect(findings).toEqual([]);
  });

  it('flags DATABASE_URL anywhere, including the Prisma schema and env templates', () => {
    const findings = scanForServerSecrets([
      file('prisma/schema.prisma', 'url = env("DATABASE_URL")'),
      file('docker/.env.example', 'DATABASE_URL=postgresql://localhost/db'),
    ]);

    expect(findings).toEqual([
      { path: 'prisma/schema.prisma', line: 1, rule: 'server-secret-env', match: 'DATABASE_URL' },
      { path: 'docker/.env.example', line: 1, rule: 'server-secret-env', match: 'DATABASE_URL' },
    ]);
  });

  it.each([
    'STRIPE_SECRET_KEY',
    'STRIPE_WEBHOOK_SECRET',
    'FIREBASE_ADMIN_PRIVATE_KEY',
    'FIREBASE_ADMIN_CLIENT_EMAIL',
    'RESEND_API_KEY',
    'NEXTAUTH_SECRET',
  ])('flags the server secret %s', (name) => {
    const findings = scanForServerSecrets([file('src/lib/x.ts', `process.env['${name}']`)]);

    expect(findings.map((f) => f.match)).toEqual([name]);
  });

  it('does not flag names that merely contain a secret name as a substring', () => {
    const findings = scanForServerSecrets([
      file(
        'src/lib/x.ts',
        'const NEXT_PUBLIC_STRIPE_SECRET_KEY_HINT = 1; const MY_DATABASE_URL_LABEL = 2;'
      ),
    ]);

    expect(findings).toEqual([]);
  });

  it('flags Prisma and firebase-admin imports with their line numbers', () => {
    const findings = scanForServerSecrets([
      file(
        'src/lib/db/client.ts',
        [
          "import { PrismaClient } from '@prisma/client';",
          'const a = 1;',
          "import { db } from '@/lib/db/client';",
        ].join('\n')
      ),
      file('src/lib/firebase/admin.ts', "import admin from 'firebase-admin';"),
    ]);

    expect(findings).toEqual([
      { path: 'src/lib/db/client.ts', line: 1, rule: 'prisma-import', match: '@prisma/client' },
      { path: 'src/lib/db/client.ts', line: 3, rule: 'prisma-import', match: '@/lib/db/client' },
      {
        path: 'src/lib/firebase/admin.ts',
        line: 1,
        rule: 'firebase-admin-import',
        match: 'firebase-admin',
      },
    ]);
  });

  it('flags firebase-admin subpath imports and require calls', () => {
    const findings = scanForServerSecrets([
      file(
        'src/a.ts',
        "import { getAuth } from 'firebase-admin/auth';\nconst p = require('@prisma/client');"
      ),
    ]);

    expect(findings.map((f) => f.rule)).toEqual(['firebase-admin-import', 'prisma-import']);
  });

  it('ignores the done-check itself so its own rule list is not reported', () => {
    const findings = scanForServerSecrets([
      file('scripts/foundation-done-check.ts', "const SECRETS = ['DATABASE_URL'];"),
      file('scripts\\foundation-done-check.cli.ts', "process.env['DATABASE_URL']"),
    ]);

    expect(findings).toEqual([]);
  });

  it('only ignores the exact done-check paths, not look-alikes elsewhere', () => {
    const findings = scanForServerSecrets([
      file('src/lib/scripts/foundation-done-check-helper.ts', 'process.env.DATABASE_URL'),
    ]);

    expect(findings.map((f) => f.match)).toEqual(['DATABASE_URL']);
  });

  it.each([
    ["import '@prisma/client';", '@prisma/client'],
    ["export { db } from '@/lib/db/client';", '@/lib/db/client'],
    ["import { x } from '@prisma/client/runtime/library';", '@prisma/client/runtime/library'],
    ["import { PrismaPg } from '@prisma/adapter-pg';", '@prisma/adapter-pg'],
    ["import { db } from '../db/client';", '../db/client'],
    ["vi.mock('@/lib/db/client', () => ({}));", '@/lib/db/client'],
  ])('flags database access in %s', (source, match) => {
    const findings = scanForServerSecrets([file('src/lib/a.ts', source)]);

    expect(findings).toEqual([{ path: 'src/lib/a.ts', line: 1, rule: 'prisma-import', match }]);
  });

  it('flags unlisted secret-looking env vars but not public or build-time ones', () => {
    const findings = scanForServerSecrets([
      file(
        'src/lib/a.ts',
        [
          'process.env.GOOGLE_CLIENT_SECRET',
          'process.env.UPSTASH_REDIS_REST_TOKEN',
          'process.env.NEXT_PUBLIC_MAPS_API_KEY',
          'process.env.SENTRY_AUTH_TOKEN',
          'process.env.TEST_USER_PASSWORD',
          'process.env.BACKEND_INTERNAL_KEY',
        ].join('\n')
      ),
      file('docker/.env.example', 'OPENAI_API_KEY=\nNEXT_PUBLIC_APP_URL=http://localhost:3000'),
    ]);

    expect(findings.map((f) => `${f.path}:${f.line}:${f.match}`)).toEqual([
      'src/lib/a.ts:1:GOOGLE_CLIENT_SECRET',
      'src/lib/a.ts:2:UPSTASH_REDIS_REST_TOKEN',
      'docker/.env.example:1:OPENAI_API_KEY',
    ]);
  });

  it('flags dynamic process.env access, which a name list cannot see', () => {
    const findings = scanForServerSecrets([
      file(
        'src/lib/a.ts',
        "const v = process.env[name];\nconst ok = process.env['NEXT_PUBLIC_X'];"
      ),
    ]);

    expect(findings).toEqual([
      { path: 'src/lib/a.ts', line: 1, rule: 'dynamic-env-access', match: 'process.env[name]' },
    ]);
  });

  it('flags committed env files other than .env.example', () => {
    const findings = scanForServerSecrets([
      file('.env', 'NEXT_PUBLIC_APP_URL=x'),
      file('config/.env.production', ''),
      file('.env.example', 'NEXT_PUBLIC_APP_URL=x'),
    ]);

    expect(findings).toEqual([
      { path: '.env', line: 0, rule: 'committed-env-file', match: '.env' },
      {
        path: 'config/.env.production',
        line: 0,
        rule: 'committed-env-file',
        match: '.env.production',
      },
    ]);
  });

  it.each([
    ["import Stripe from 'stripe';", 'stripe'],
    ["const Stripe = require('stripe');", 'stripe'],
    ["import { x } from 'stripe/cjs/stripe.core';", 'stripe/cjs/stripe.core'],
    ["import { getStripeServerClient } from '@/lib/stripe/server';", '@/lib/stripe/server'],
  ])('flags the Stripe server SDK in %s', (source, match) => {
    const findings = scanForServerSecrets([file('src/lib/a.ts', source)]);

    expect(findings).toEqual([{ path: 'src/lib/a.ts', line: 1, rule: 'stripe-import', match }]);
  });

  it('does not flag the client-side Stripe SDK or look-alike module names', () => {
    const findings = scanForServerSecrets([
      file(
        'src/lib/a.ts',
        "import { loadStripe } from '@stripe/stripe-js';\nimport x from '@/lib/stripe/return-urls';\nimport y from 'stripe-utils';"
      ),
    ]);

    expect(findings).toEqual([]);
  });

  it('flags the removed firebase-admin wrapper module', () => {
    const findings = scanForServerSecrets([
      file('src/a.ts', "import { getAdminAuth } from '@/lib/firebase/admin';"),
    ]);

    expect(findings.map((f) => f.rule)).toEqual(['firebase-admin-import']);
  });

  it.each([
    ['const { STRIPE_SECRET_KEY } = process.env;', 'STRIPE_SECRET_KEY'],
    ['const { MY_SERVICE_API_KEY: key } = process.env;', 'MY_SERVICE_API_KEY'],
    ['const { A_TOKEN = "x" } = process.env as Record<string, string>;', 'A_TOKEN'],
    ['let { NEXT_PUBLIC_X, SOME_PRIVATE_KEY } = process.env;', 'SOME_PRIVATE_KEY'],
  ])('flags a destructured process.env read: %s', (source, match) => {
    const findings = scanForServerSecrets([file('src/lib/a.ts', source)]);

    expect(findings.map((f) => f.match)).toEqual([match]);
  });

  it('flags a multi-line destructured read on the line of the secret', () => {
    const findings = scanForServerSecrets([
      file(
        'src/lib/a.ts',
        ['const {', '  NEXT_PUBLIC_OK,', '  HIDDEN_SECRET,', '} = process.env;'].join('\n')
      ),
    ]);

    expect(findings).toEqual([
      { path: 'src/lib/a.ts', line: 3, rule: 'server-secret-env', match: 'HIDDEN_SECRET' },
    ]);
  });

  it('does not flag destructuring of public variables or of other objects', () => {
    const findings = scanForServerSecrets([
      file(
        'src/lib/a.ts',
        'const { NEXT_PUBLIC_APP_URL } = process.env;\nconst { API_KEY } = config;'
      ),
    ]);

    expect(findings).toEqual([]);
  });

  it('allows the e2e Firebase service account only in the e2e account tooling', () => {
    const tooling = scanForServerSecrets([
      file('scripts/e2e-accounts.mjs', 'env.FIREBASE_ADMIN_PRIVATE_KEY'),
      file('scripts/e2e-env.cjs', "'FIREBASE_ADMIN_PROJECT_ID'"),
    ]);
    const elsewhere = scanForServerSecrets([
      file('src/lib/a.ts', 'process.env.FIREBASE_ADMIN_PRIVATE_KEY'),
      file('scripts/e2e-accounts.mjs', 'process.env.STRIPE_SECRET_KEY'),
    ]);

    expect(tooling).toEqual([]);
    expect(elsewhere.map((f) => `${f.path}:${f.match}`)).toEqual([
      'src/lib/a.ts:FIREBASE_ADMIN_PRIVATE_KEY',
      'scripts/e2e-accounts.mjs:STRIPE_SECRET_KEY',
    ]);
  });

  it('applies the e2e tooling allowance to destructured reads too', () => {
    const findings = scanForServerSecrets([
      file('scripts/e2e-env.cjs', 'const { FIREBASE_ADMIN_PRIVATE_KEY } = process.env;'),
      file('src/lib/a.ts', 'const { FIREBASE_ADMIN_PRIVATE_KEY } = process.env;'),
    ]);

    expect(findings.map((f) => f.path)).toEqual(['src/lib/a.ts']);
  });

  it('flags server-only dependencies in package.json', () => {
    const pkg = JSON.stringify({
      dependencies: {
        next: '16.0.0',
        '@prisma/client': '6.0.0',
        'firebase-admin': '13.0.0',
        stripe: '18.0.0',
        '@stripe/stripe-js': '5.0.0',
      },
      devDependencies: { prisma: '6.0.0' },
    });

    const findings = scanForServerSecrets([file('package.json', pkg)]);

    expect(findings.map((f) => `${f.rule}:${f.match}`)).toEqual([
      'server-only-dependency:@prisma/client',
      'server-only-dependency:firebase-admin',
      'server-only-dependency:stripe',
      'server-only-dependency:prisma',
    ]);
  });

  it('reports every match on a line and handles CRLF line endings', () => {
    const findings = scanForServerSecrets([
      file(
        'src/a.ts',
        'ok\r\nconst a = [process.env.STRIPE_SECRET_KEY, process.env.DATABASE_URL];'
      ),
    ]);

    expect(findings.map((f) => `${f.line}:${f.match}`)).toEqual([
      '2:STRIPE_SECRET_KEY',
      '2:DATABASE_URL',
    ]);
  });
});

describe('runDoneCheck', () => {
  const cleanFiles = [file('src/app/page.tsx', 'export default function Page() { return null; }')];

  it('fails on secret findings without calling the backend or running e2e', async () => {
    const checkHealth = vi.fn();
    const runE2E = vi.fn();

    const result = await runDoneCheck({
      files: [file('docker/.env.example', 'DATABASE_URL=x')],
      backendUrl: 'http://localhost:8000',
      checkHealth,
      runE2E,
    });

    expect(result.ok).toBe(false);
    expect(result.findings).toHaveLength(1);
    expect(checkHealth).not.toHaveBeenCalled();
    expect(runE2E).not.toHaveBeenCalled();
  });

  it('fails when no FastAPI URL is configured, because e2e must run against FastAPI', async () => {
    const runE2E = vi.fn();

    const result = await runDoneCheck({
      files: cleanFiles,
      backendUrl: undefined,
      checkHealth: vi.fn(),
      runE2E,
    });

    expect(result).toMatchObject({ ok: false, reason: expect.stringContaining('BACKEND_API_URL') });
    expect(runE2E).not.toHaveBeenCalled();
  });

  it('fails when the FastAPI health check does not pass', async () => {
    const runE2E = vi.fn();

    const result = await runDoneCheck({
      files: cleanFiles,
      backendUrl: 'http://localhost:8000/',
      checkHealth: vi.fn().mockResolvedValue(false),
      runE2E,
    });

    expect(result).toMatchObject({
      ok: false,
      reason: expect.stringContaining('http://localhost:8000/health'),
    });
    expect(runE2E).not.toHaveBeenCalled();
  });

  it('runs e2e against FastAPI and reports its result', async () => {
    const runE2E = vi.fn().mockResolvedValue(0);

    const passed = await runDoneCheck({
      files: cleanFiles,
      backendUrl: 'http://localhost:8000',
      checkHealth: vi.fn().mockResolvedValue(true),
      runE2E,
    });

    expect(runE2E).toHaveBeenCalledWith('http://localhost:8000');
    expect(passed).toEqual({ ok: true, findings: [] });

    const failed = await runDoneCheck({
      files: cleanFiles,
      backendUrl: 'http://localhost:8000',
      checkHealth: vi.fn().mockResolvedValue(true),
      runE2E: vi.fn().mockResolvedValue(1),
    });

    expect(failed).toMatchObject({ ok: false, reason: expect.stringContaining('e2e') });
  });

  it('turns a crashing e2e run into a failure, never a pass', async () => {
    const result = await runDoneCheck({
      files: cleanFiles,
      backendUrl: 'http://localhost:8000',
      checkHealth: vi.fn().mockResolvedValue(true),
      runE2E: vi.fn().mockRejectedValue(new Error('spawn npx ENOENT')),
    });

    expect(result).toMatchObject({
      ok: false,
      reason: expect.stringContaining('spawn npx ENOENT'),
    });
  });
});

describe('pending template cleanup', () => {
  it('does not scan the coordinator-owned .env.example template (remove once it is clean)', () => {
    const findings = scanForServerSecrets([
      file('.env.example', 'DATABASE_URL=x\nSTRIPE_SECRET_KEY=y'),
    ]);

    expect(findings).toEqual([]);
  });
});
