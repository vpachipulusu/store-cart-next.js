import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

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
