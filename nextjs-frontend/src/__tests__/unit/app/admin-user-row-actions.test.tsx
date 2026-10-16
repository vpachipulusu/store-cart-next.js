import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { UserRowActions } from '@/app/(admin)/admin/users/user-row-actions';

describe('UserRowActions', () => {
  it('lists View Details linking to the user page, plus Edit and Suspend', async () => {
    const user = userEvent.setup();
    render(<UserRowActions userId="user-123" />);

    await user.click(screen.getByRole('button', { name: /open menu/i }));

    const viewDetails = await screen.findByRole('menuitem', { name: /view details/i });
    expect(viewDetails).toHaveAttribute('href', '/admin/users/user-123');
    expect(screen.getByRole('menuitem', { name: /edit user/i })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: /suspend user/i })).toBeInTheDocument();
  });

  it('names the trigger after the user when a label is given', () => {
    render(<UserRowActions userId="user-123" userLabel="Ada" />);

    expect(screen.getByRole('button', { name: 'Open menu for Ada' })).toBeInTheDocument();
  });
});
