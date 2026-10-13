import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const mocks = vi.hoisted(() => ({
  getUserProfileAction: vi.fn(),
}));

vi.mock('@/app/actions/user-actions', () => ({
  getUserProfileAction: mocks.getUserProfileAction,
  updateUserProfileAction: vi.fn(),
  updateUserAvatarAction: vi.fn(),
}));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }));

import ProfilePage from '@/app/dashboard/profile/page';

const PROFILE_USER = {
  email: 'person@example.test',
  displayName: 'Person',
  bio: '',
  location: '',
  website: '',
  phoneNumber: '',
  avatarUrl: '',
};

describe('ProfilePage form labels', () => {
  it('gives every profile field an accessible name, with the email input read-only', async () => {
    mocks.getUserProfileAction.mockResolvedValue({ success: true, data: { user: PROFILE_USER } });

    render(<ProfilePage />);

    const email = await screen.findByLabelText('Email');
    expect(email).toHaveValue(PROFILE_USER.email);
    expect(email).toBeDisabled();

    for (const name of ['Display Name', 'Bio', 'Location', 'Website', 'Phone Number']) {
      expect(screen.getByLabelText(name)).toBeInTheDocument();
    }
  });
});

describe('ProfilePage website validation', () => {
  it('shows the application message for an invalid website URL instead of native validation', async () => {
    mocks.getUserProfileAction.mockResolvedValue({ success: true, data: { user: PROFILE_USER } });
    const user = userEvent.setup();

    render(<ProfilePage />);

    const website = await screen.findByLabelText('Website');
    await user.type(website, 'not-a-url');
    await user.click(screen.getByRole('button', { name: /save changes/i }));

    expect(await screen.findByText('Must be a valid URL')).toBeInTheDocument();
    await waitFor(() => expect(website).toHaveAttribute('aria-invalid', 'true'));
    expect(website).toHaveAccessibleDescription(/valid url/i);
  });
});
