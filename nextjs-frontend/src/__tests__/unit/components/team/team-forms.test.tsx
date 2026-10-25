import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const mocks = vi.hoisted(() => ({
  inviteTeamMemberAction: vi.fn(),
  acceptInvitationAction: vi.fn(),
}));

vi.mock('@/app/actions/team-actions', () => ({
  inviteTeamMemberAction: mocks.inviteTeamMemberAction,
  acceptInvitationAction: mocks.acceptInvitationAction,
}));

import { InviteMemberForm } from '@/components/team/invite-member-form';
import { AcceptInvitationButton } from '@/components/team/accept-invitation-button';

const LINK = 'https://app.test/invite/AbC_def-1234567890ghijklmnop';

beforeEach(() => {
  vi.clearAllMocks();
});

describe('InviteMemberForm', () => {
  it('sends the invitation and shows the link once', async () => {
    mocks.inviteTeamMemberAction.mockResolvedValue({
      success: true,
      data: { email: 'new@example.com', acceptUrl: LINK, emailSent: true },
    });
    const user = userEvent.setup();
    render(<InviteMemberForm />);

    await user.type(screen.getByLabelText('Email address'), 'new@example.com');
    await user.selectOptions(screen.getByLabelText('Role'), 'ADMIN');
    await user.click(screen.getByRole('button', { name: 'Send invitation' }));

    expect(mocks.inviteTeamMemberAction).toHaveBeenCalledWith({
      email: 'new@example.com',
      role: 'ADMIN',
    });
    expect(await screen.findByText('Invitation sent to new@example.com.')).toBeInTheDocument();
    expect(screen.getByLabelText('Invitation link')).toHaveValue(LINK);
    expect(screen.getByLabelText('Email address')).toHaveValue('');
  });

  it('says when the email could not be sent and copies the link', async () => {
    mocks.inviteTeamMemberAction.mockResolvedValue({
      success: true,
      data: { email: 'new@example.com', acceptUrl: LINK, emailSent: false },
    });
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue();
    render(<InviteMemberForm />);

    await user.type(screen.getByLabelText('Email address'), 'new@example.com');
    await user.click(screen.getByRole('button', { name: 'Send invitation' }));
    expect(await screen.findByText(/the email could not be sent/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Copy link' }));

    expect(writeText).toHaveBeenCalledWith(LINK);
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument();
  });

  it('keeps working when the clipboard is refused', async () => {
    mocks.inviteTeamMemberAction.mockResolvedValue({
      success: true,
      data: { email: 'new@example.com', acceptUrl: LINK, emailSent: true },
    });
    const user = userEvent.setup();
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('denied'));
    render(<InviteMemberForm />);

    await user.type(screen.getByLabelText('Email address'), 'new@example.com');
    await user.click(screen.getByRole('button', { name: 'Send invitation' }));
    await user.click(await screen.findByRole('button', { name: 'Copy link' }));

    expect(screen.getByRole('button', { name: 'Copy link' })).toBeInTheDocument();
  });

  it('shows the error from the action', async () => {
    mocks.inviteTeamMemberAction.mockResolvedValue({
      success: false,
      error: 'Already a member of this organization',
    });
    const user = userEvent.setup();
    render(<InviteMemberForm />);

    await user.type(screen.getByLabelText('Email address'), 'staff@example.com');
    await user.selectOptions(screen.getByLabelText('Role'), 'STAFF');
    await user.click(screen.getByRole('button', { name: 'Send invitation' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Already a member of this organization'
    );
    expect(screen.queryByLabelText('Invitation link')).not.toBeInTheDocument();
  });
});

describe('AcceptInvitationButton', () => {
  it('accepts only when clicked, then links to the dashboard', async () => {
    mocks.acceptInvitationAction.mockResolvedValue({ success: true, data: { role: 'STAFF' } });
    const user = userEvent.setup();
    render(<AcceptInvitationButton token="tok_1234567890abcdef" />);
    expect(mocks.acceptInvitationAction).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Accept invitation' }));

    expect(mocks.acceptInvitationAction).toHaveBeenCalledWith('tok_1234567890abcdef');
    expect(await screen.findByText('You have joined the team.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Go to the dashboard' })).toHaveAttribute(
      'href',
      '/dashboard'
    );
  });

  it('shows why the invitation could not be accepted', async () => {
    mocks.acceptInvitationAction.mockResolvedValue({
      success: false,
      error: 'This invitation is invalid, has already been used or has expired.',
    });
    const user = userEvent.setup();
    render(<AcceptInvitationButton token="tok_1234567890abcdef" />);

    await user.click(screen.getByRole('button', { name: 'Accept invitation' }));

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('has already been used')
    );
    expect(screen.getByRole('button', { name: 'Accept invitation' })).toBeEnabled();
  });
});
