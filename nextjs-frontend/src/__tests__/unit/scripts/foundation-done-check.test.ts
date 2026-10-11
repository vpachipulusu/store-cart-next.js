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
      file('.env.example', 'DATABASE_URL=postgresql://localhost/db'),
    ]);

    expect(findings).toEqual([
      { path: 'prisma/schema.prisma', line: 1, rule: 'server-secret-env', match: 'DATABASE_URL' },
      { path: '.env.example', line: 1, rule: 'server-secret-env', match: 'DATABASE_URL' },
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
      file('.env.example', 'OPENAI_API_KEY=\nNEXT_PUBLIC_APP_URL=http://localhost:3000'),
    ]);

    expect(findings.map((f) => `${f.path}:${f.line}:${f.match}`)).toEqual([
      'src/lib/a.ts:1:GOOGLE_CLIENT_SECRET',
      'src/lib/a.ts:2:UPSTASH_REDIS_REST_TOKEN',
      '.env.example:1:OPENAI_API_KEY',
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

  it('flags server-only dependencies in package.json', () => {
    const pkg = JSON.stringify({
      dependencies: { next: '16.0.0', '@prisma/client': '6.0.0', 'firebase-admin': '13.0.0' },
      devDependencies: { prisma: '6.0.0' },
    });

    const findings = scanForServerSecrets([file('package.json', pkg)]);

    expect(findings.map((f) => `${f.rule}:${f.match}`)).toEqual([
      'server-only-dependency:@prisma/client',
      'server-only-dependency:firebase-admin',
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
      files: [file('.env.example', 'DATABASE_URL=x')],
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
