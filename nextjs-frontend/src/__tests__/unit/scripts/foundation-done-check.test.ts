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
      file('src/app/page.tsx', "const key = process.env.NEXT_PUBLIC_FIREBASE_API_KEY;"),
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
      file('src/lib/x.ts', 'const NEXT_PUBLIC_STRIPE_SECRET_KEY_HINT = 1; const MY_DATABASE_URL_LABEL = 2;'),
    ]);

    expect(findings).toEqual([]);
  });

  it('flags Prisma and firebase-admin imports with their line numbers', () => {
    const findings = scanForServerSecrets([
      file(
        'src/lib/db/client.ts',
        ["import { PrismaClient } from '@prisma/client';", 'const a = 1;', "import { db } from '@/lib/db/client';"].join('\n'),
      ),
      file('src/lib/firebase/admin.ts', "import admin from 'firebase-admin';"),
    ]);

    expect(findings).toEqual([
      { path: 'src/lib/db/client.ts', line: 1, rule: 'prisma-import', match: '@prisma/client' },
      { path: 'src/lib/db/client.ts', line: 3, rule: 'prisma-import', match: '@/lib/db/client' },
      { path: 'src/lib/firebase/admin.ts', line: 1, rule: 'firebase-admin-import', match: 'firebase-admin' },
    ]);
  });

  it('flags firebase-admin subpath imports and require calls', () => {
    const findings = scanForServerSecrets([
      file('src/a.ts', "import { getAuth } from 'firebase-admin/auth';\nconst p = require('@prisma/client');"),
    ]);

    expect(findings.map((f) => f.rule)).toEqual(['firebase-admin-import', 'prisma-import']);
  });

  it('ignores the done-check itself so its own rule list is not reported', () => {
    const findings = scanForServerSecrets([
      file('scripts/foundation-done-check.ts', "const SECRETS = ['DATABASE_URL'];"),
    ]);

    expect(findings).toEqual([]);
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

    const result = await runDoneCheck({ files: cleanFiles, backendUrl: undefined, checkHealth: vi.fn(), runE2E });

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

    expect(result).toMatchObject({ ok: false, reason: expect.stringContaining('http://localhost:8000/health') });
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
});
