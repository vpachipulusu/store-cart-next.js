import { describe, expect, it, vi } from 'vitest';
import {
  assertThrowawayAccountDeleted,
  deleteThrowawayAccount,
} from '../../../../scripts/e2e-accounts.mjs';

const account = {
  email: 'e2e-temp-123456789abc@example.com',
  uid: 'test-only-user',
};

function clients() {
  return {
    auth: {
      deleteUser: vi.fn().mockResolvedValue(undefined),
      getUser: vi.fn().mockRejectedValue({ code: 'auth/user-not-found' }),
    },
    prisma: {
      user: {
        deleteMany: vi.fn().mockResolvedValue({ count: 0 }),
        count: vi.fn().mockResolvedValue(0),
      },
    },
  };
}

describe('throwaway-account cleanup', () => {
  it('verifies Firebase and database absence before fixture cleanup', async () => {
    const testClients = clients();
    await expect(assertThrowawayAccountDeleted(testClients, account)).resolves.toBeUndefined();
    expect(testClients.auth.getUser).toHaveBeenCalledWith(account.uid);
    expect(testClients.prisma.user.count).toHaveBeenCalledWith({
      where: { firebaseUid: account.uid },
    });
    expect(testClients.auth.deleteUser).not.toHaveBeenCalled();
    expect(testClients.prisma.user.deleteMany).not.toHaveBeenCalled();
  });

  it('rejects a logout-only implementation that leaves the Firebase account', async () => {
    const testClients = clients();
    testClients.auth.getUser.mockResolvedValue({ uid: account.uid });
    await expect(assertThrowawayAccountDeleted(testClients, account)).rejects.toThrow(
      /Firebase account still exists/
    );
  });

  it('rejects residual database data after Firebase deletion', async () => {
    const testClients = clients();
    testClients.prisma.user.count.mockResolvedValue(1);
    await expect(assertThrowawayAccountDeleted(testClients, account)).rejects.toThrow(
      /database account still exists/
    );
  });

  it('does not treat Firebase lookup outages as proof of account deletion', async () => {
    const testClients = clients();
    const failure = { code: 'auth/internal-error' };
    testClients.auth.getUser.mockRejectedValue(failure);
    await expect(assertThrowawayAccountDeleted(testClients, account)).rejects.toBe(failure);
  });
  it('cleans up an account already deleted through the browser', async () => {
    const testClients = clients();
    testClients.auth.deleteUser.mockRejectedValue({ code: 'auth/user-not-found' });
    await expect(deleteThrowawayAccount(testClients, account)).resolves.toBeUndefined();
    expect(testClients.prisma.user.deleteMany).toHaveBeenCalledWith({
      where: { firebaseUid: account.uid },
    });
    expect(testClients.auth.deleteUser).toHaveBeenCalledWith(account.uid);
  });

  it('propagates Firebase failures other than an already missing account', async () => {
    const testClients = clients();
    const failure = { code: 'auth/internal-error' };
    testClients.auth.deleteUser.mockRejectedValue(failure);
    await expect(deleteThrowawayAccount(testClients, account)).rejects.toBe(failure);
  });

  it('propagates database cleanup failures', async () => {
    const testClients = clients();
    const failure = new Error('test database unavailable');
    testClients.prisma.user.deleteMany.mockRejectedValue(failure);
    await expect(deleteThrowawayAccount(testClients, account)).rejects.toBe(failure);
    expect(testClients.auth.deleteUser).not.toHaveBeenCalled();
  });

  it.each([
    'merchant@example.com',
    'e2e-user-123456789abc@example.com',
    'e2e-temp-invalid@example.com',
  ])('refuses cleanup for a non-throwaway identity: %s', async (email) => {
    const testClients = clients();
    await expect(deleteThrowawayAccount(testClients, { ...account, email })).rejects.toThrow(
      /Refusing to (delete|touch)/
    );
    expect(testClients.prisma.user.deleteMany).not.toHaveBeenCalled();
    expect(testClients.auth.deleteUser).not.toHaveBeenCalled();
  });
});
