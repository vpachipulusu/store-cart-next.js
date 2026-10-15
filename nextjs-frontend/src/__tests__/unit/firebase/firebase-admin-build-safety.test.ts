// @vitest-environment node
/**
 * Regression tests for KAN-136: `next build` imports every route and server-action module while collecting page
 * data, so no module may initialise the Firebase Admin SDK at import time. A build must not need FIREBASE_ADMIN_*.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('next/headers', () => ({ cookies: vi.fn(), headers: vi.fn() }));
vi.mock('next/cache', () => ({
  revalidatePath: vi.fn(),
  revalidateTag: vi.fn(),
  unstable_cache: (fn: unknown) => fn,
}));
vi.mock('@/lib/db/client', () => ({ db: {} }));
vi.mock('@/lib/logger', () => ({ logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn() } }));
vi.mock('@/lib/firebase/client', () => ({ auth: {} }));
vi.mock('@/lib/utils/notifications', () => ({}));

const SECRET_NAMES = [
  'FIREBASE_ADMIN_PROJECT_ID',
  'FIREBASE_ADMIN_CLIENT_EMAIL',
  'FIREBASE_ADMIN_PRIVATE_KEY',
] as const;

describe('KAN-136: Firebase Admin is initialised on first use, not at import', () => {
  let saved: Record<string, string | undefined>;

  beforeEach(() => {
    saved = Object.fromEntries(SECRET_NAMES.map((name) => [name, process.env[name]]));
    SECRET_NAMES.forEach((name) => delete process.env[name]);
    vi.resetModules();
    // vitest.setup.ts mocks firebase-admin globally; use the real SDK here so that `cert()` without credentials
    // throws exactly as it does during `next build`.
    vi.doUnmock('firebase-admin/app');
    vi.doUnmock('firebase-admin/auth');
  });

  afterEach(() => {
    SECRET_NAMES.forEach((name) => {
      if (saved[name] === undefined) delete process.env[name];
      else process.env[name] = saved[name];
    });
  });

  it.each([
    ['Firebase Admin module', '@/lib/firebase/admin'],
    ['auth actions', '@/app/actions/auth-actions'],
    ['admin user actions', '@/app/actions/admin/user-actions'],
    ['pricing page', '@/app/pricing/page'],
  ])('imports the %s without Firebase Admin credentials', async (_name, modulePath) => {
    await expect(import(modulePath)).resolves.toBeDefined();
  });

  it('no longer exports module-scope admin app or auth instances', async () => {
    const admin = await import('@/lib/firebase/admin');
    expect(admin).not.toHaveProperty('adminApp');
    expect(admin).not.toHaveProperty('adminAuth');
  });

  it('fails clearly at first use when credentials are missing', async () => {
    const { getAdminAuth } = await import('@/lib/firebase/admin');
    expect(() => getAdminAuth()).toThrow(
      /FIREBASE_ADMIN_PROJECT_ID.*FIREBASE_ADMIN_CLIENT_EMAIL.*FIREBASE_ADMIN_PRIVATE_KEY/
    );
  });
});

describe('KAN-136: Firebase Admin initialisation when credentials are set', () => {
  const initializeApp = vi.fn((options: unknown) => ({ name: '[DEFAULT]', options }));
  const getApps = vi.fn((): unknown[] => []);
  const cert = vi.fn((serviceAccount: unknown) => ({ serviceAccount }));
  const getAuth = vi.fn((app: unknown) => ({ app }));

  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    getApps.mockReturnValue([]);
    vi.doMock('firebase-admin/app', () => ({ initializeApp, getApps, cert }));
    vi.doMock('firebase-admin/auth', () => ({ getAuth }));
    vi.stubEnv('FIREBASE_ADMIN_PROJECT_ID', 'test-project');
    vi.stubEnv('FIREBASE_ADMIN_CLIENT_EMAIL', 'admin@test-project.iam.gserviceaccount.com');
    vi.stubEnv('FIREBASE_ADMIN_PRIVATE_KEY', 'line-1\\nline-2');
  });

  afterEach(() => {
    vi.doUnmock('firebase-admin/app');
    vi.doUnmock('firebase-admin/auth');
    vi.unstubAllEnvs();
  });

  it('does not touch the SDK at import', async () => {
    await import('@/lib/firebase/admin');
    expect(initializeApp).not.toHaveBeenCalled();
    expect(getAuth).not.toHaveBeenCalled();
  });

  it('initialises once with the credentials, unescaping the private key, and reuses the auth instance', async () => {
    const { getAdminAuth } = await import('@/lib/firebase/admin');

    const first = getAdminAuth();

    expect(first).toBe(getAdminAuth());
    expect(initializeApp).toHaveBeenCalledTimes(1);
    expect(cert).toHaveBeenCalledWith({
      projectId: 'test-project',
      clientEmail: 'admin@test-project.iam.gserviceaccount.com',
      privateKey: 'line-1\nline-2',
    });
  });

  it('reuses an existing app instead of initialising twice', async () => {
    const existing = { name: '[DEFAULT]' };
    getApps.mockReturnValue([existing]);
    const { getAdminApp } = await import('@/lib/firebase/admin');

    expect(getAdminApp()).toBe(existing);
    expect(initializeApp).not.toHaveBeenCalled();
  });
});
