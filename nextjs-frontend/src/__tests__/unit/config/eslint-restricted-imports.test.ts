// @vitest-environment node
import { ESLint } from 'eslint';
import path from 'node:path';
import { beforeAll, describe, expect, it } from 'vitest';

/**
 * Pins the import restrictions in eslint.config.mjs (KAN-51, KAN-208): the frontend must never depend on Prisma,
 * Stripe or the Firebase Admin SDK again, there is no allow-list, and the generated API client is reachable only
 * from src/lib/api and tests. Each case lints a snippet as if it lived at `filePath`.
 */

const FRONTEND_ROOT = path.resolve(__dirname, '../../../..');
const RULE = 'no-restricted-imports';

const eslint = new ESLint({ cwd: FRONTEND_ROOT });

async function restrictedImportMessages(code: string, filePath: string): Promise<string[]> {
  const [result] = await eslint.lintText(code, { filePath: path.join(FRONTEND_ROOT, filePath) });
  return result.messages.filter((m) => m.ruleId === RULE).map((m) => m.message);
}

const CONFIG_LOAD_TIMEOUT_MS = 60_000;

describe('eslint restricted imports', () => {
  // The first lint loads the whole Next.js flat config, which is slow on a cold machine.
  beforeAll(async () => {
    await restrictedImportMessages('export {};', 'src/lib/warmup.ts');
  }, CONFIG_LOAD_TIMEOUT_MS);

  it.each([
    ["import Stripe from 'stripe';", 'stripe'],
    ["import { getAuth } from 'firebase-admin/auth';", 'firebase-admin/auth'],
    ["import admin from 'firebase-admin';", 'firebase-admin'],
    ["import { getAdminAuth } from '@/lib/firebase/admin';", '@/lib/firebase/admin'],
    ["import { getStripeServerClient } from '@/lib/stripe/server';", '@/lib/stripe/server'],
    ["import { getAdminAuth } from '../firebase/admin';", 'a relative firebase/admin path'],
    ["import { PrismaClient } from '@prisma/client';", '@prisma/client'],
    ["import { db } from '@/lib/db/client';", '@/lib/db/client'],
  ])('rejects %s (%s)', async (code) => {
    expect(await restrictedImportMessages(code, 'src/lib/example.ts')).not.toEqual([]);
  });

  it.each([
    'src/app/actions/example.ts',
    'src/config/subscriptions.ts',
    'src/lib/auth/verified-session.ts',
    'src/components/example.tsx',
    'scripts/e2e-accounts.mjs',
  ])('has no allow-list: the Stripe server SDK is rejected in %s', async (filePath) => {
    expect(await restrictedImportMessages("import Stripe from 'stripe';", filePath)).not.toEqual(
      []
    );
  });

  it('rejects firebase-admin in scripts, which the old allow-list used to permit', async () => {
    const messages = await restrictedImportMessages(
      "import { getAuth } from 'firebase-admin/auth';",
      'scripts/example.mjs'
    );

    expect(messages).not.toEqual([]);
  });

  it.each([
    "import { loadStripe } from '@stripe/stripe-js';",
    "import { buildCheckoutReturnUrls } from '@/lib/stripe/return-urls';",
    "import { signOut } from 'firebase/auth';",
    "import { fetchSessionStatus } from '@/lib/api/account';",
    "import { z } from 'zod';",
  ])('allows %s', async (code) => {
    expect(await restrictedImportMessages(code, 'src/lib/example.ts')).toEqual([]);
  });

  describe('generated API client', () => {
    const code = "import { readPlanPrices } from '@/lib/api/generated';";

    it('is rejected outside src/lib/api and tests', async () => {
      expect(await restrictedImportMessages(code, 'src/app/example.ts')).not.toEqual([]);
      expect(await restrictedImportMessages(code, 'src/components/example.tsx')).not.toEqual([]);
    });

    it('is allowed in the server-only wrappers and in tests', async () => {
      expect(await restrictedImportMessages(code, 'src/lib/api/example.ts')).toEqual([]);
      expect(await restrictedImportMessages(code, 'src/__tests__/unit/example.test.ts')).toEqual(
        []
      );
    });

    it('does not weaken the Stripe restriction inside src/lib/api', async () => {
      expect(
        await restrictedImportMessages("import Stripe from 'stripe';", 'src/lib/api/example.ts')
      ).not.toEqual([]);
    });
  });
});
