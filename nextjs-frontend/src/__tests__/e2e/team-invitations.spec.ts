import {
  test as base,
  configureE2eContext,
  expect,
  type ThrowawayAccount,
} from './helpers/fixtures';
import {
  ensureAccountHasStore,
  loginAsThrowawayAccount,
  loginAsThrowawayAccountOnPro,
  waitForPageReady,
} from './helpers/e2e-utils';

/**
 * KAN-62: an owner invites by email, a second user accepts once, reusing the link fails, and the new STAFF member
 * sees the permission notice on the team and billing settings.
 *
 * Needs the FastAPI backend (BACKEND_API_URL), BACKEND_INTERNAL_KEY and the saved admin session (the owner's
 * organisation is granted Pro, since Free allows one team member). Without RESEND_API_KEY the backend does not
 * send the email, so the test reads the link the page shows once after inviting.
 */

type AccountsModule = {
  createThrowawayAccount: (clients: unknown) => Promise<ThrowawayAccount>;
  deleteThrowawayAccount: (clients: unknown, account: ThrowawayAccount) => Promise<void>;
};

const test = base.extend<{ invitee: ThrowawayAccount }>({
  invitee: async ({ accountClients }, provide) => {
    const accounts = (await import('../../../scripts/e2e-accounts.mjs')) as AccountsModule;
    const account = await accounts.createThrowawayAccount(accountClients);
    try {
      await provide(account);
    } finally {
      await accounts.deleteThrowawayAccount(accountClients, account);
    }
  },
});

test.describe('Team invitations', () => {
  test.skip(
    !process.env.BACKEND_INTERNAL_KEY,
    'Skipped: BACKEND_INTERNAL_KEY / BACKEND_API_URL not set (needs FastAPI)'
  );

  test('owner invites, the invitee accepts once and is STAFF', async ({
    page,
    browser,
    throwawayAccount,
    invitee,
  }) => {
    // Owner: a Pro organisation with a store.
    await loginAsThrowawayAccountOnPro(page, throwawayAccount);
    await ensureAccountHasStore(page, `e2e-team-${throwawayAccount.uid.slice(0, 8).toLowerCase()}`);

    await page.goto('/dashboard/settings/team');
    await waitForPageReady(page);
    await expect(page.getByRole('heading', { name: 'Team', level: 1 })).toBeVisible();
    await page.getByLabel('Email address').fill(invitee.email);
    await page.getByLabel('Role').selectOption('STAFF');
    await page.getByRole('button', { name: 'Send invitation' }).click();

    const linkField = page.getByLabel('Invitation link');
    await expect(linkField).toHaveValue(/\/invite\/[A-Za-z0-9_-]{40,}$/);
    const invitePath = new URL(await linkField.inputValue()).pathname;
    await page.reload();
    await expect(page.getByRole('list', { name: 'Pending invitations' })).toContainText(
      invitee.email
    );
    await expect(page.getByLabel('Invitation link')).toHaveCount(0);

    // Invitee: a separate browser context, signed in as the invited address.
    const inviteeContext = await browser.newContext();
    await configureE2eContext(inviteeContext);
    const inviteePage = await inviteeContext.newPage();
    try {
      await inviteePage.goto(invitePath);
      await expect(inviteePage.getByRole('link', { name: 'Sign in' })).toBeVisible();

      await loginAsThrowawayAccount(inviteePage, invitee);
      await inviteePage.goto(invitePath);
      await inviteePage.getByRole('button', { name: 'Accept invitation' }).click();
      await expect(inviteePage.getByText('You have joined the team.')).toBeVisible();

      // The link works once.
      await inviteePage.goto(invitePath);
      await inviteePage.getByRole('button', { name: 'Accept invitation' }).click();
      await expect(inviteePage.getByRole('alert')).toContainText(
        'invalid, has already been used or has expired'
      );

      // STAFF cannot open team or billing settings.
      for (const path of ['/dashboard/settings/team', '/dashboard/settings/billing']) {
        await inviteePage.goto(path);
        await waitForPageReady(inviteePage);
        await expect(inviteePage.getByRole('alert')).toContainText('You do not have access');
      }
    } finally {
      await inviteeContext.close();
    }

    // The owner now sees the new member.
    await page.reload();
    await expect(page.getByRole('list', { name: 'Members' })).toContainText(invitee.email);
  });
});
