import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const mocks = vi.hoisted(() => ({
  getUserSettingsAction: vi.fn(),
  updateUserSettingsAction: vi.fn(),
  toast: vi.fn(),
}));

vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }) }));
vi.mock('@/app/actions/user-actions', () => ({
  getUserSettingsAction: mocks.getUserSettingsAction,
  updateUserSettingsAction: mocks.updateUserSettingsAction,
}));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: mocks.toast }) }));

import SettingsPage from '@/app/dashboard/settings/page';

const SETTINGS = { theme: 'dark', emailNotifications: true, language: 'fr', timezone: 'UTC' };

beforeEach(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  );
  vi.clearAllMocks();
  mocks.getUserSettingsAction.mockResolvedValue({ success: true, data: { settings: SETTINGS } });
});

describe('SettingsPage structure', () => {
  it('renders exactly one h1 with each section as an h2', async () => {
    render(<SettingsPage />);

    expect(await screen.findByRole('heading', { level: 1, name: 'Settings' })).toBeInTheDocument();
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    for (const name of ['Appearance', 'Notifications', 'Regional Settings']) {
      expect(screen.getByRole('heading', { level: 2, name })).toBeInTheDocument();
    }
  });

  it('marks the page busy while settings load', () => {
    mocks.getUserSettingsAction.mockReturnValue(new Promise(() => {}));

    render(<SettingsPage />);

    expect(screen.getByRole('status', { name: /loading settings/i })).toHaveAttribute(
      'aria-busy',
      'true'
    );
  });

  it('gives every control an accessible name and a linked hint', async () => {
    render(<SettingsPage />);

    const theme = await screen.findByRole('combobox', { name: 'Theme' });
    expect(theme).toHaveAccessibleDescription(/preferred color theme/i);
    expect(screen.getByRole('combobox', { name: 'Language' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Timezone' })).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'Email Notifications' })).toBeChecked();
  });
});

describe('SettingsPage saving', () => {
  it('shows a Saving label while pending, then a success toast', async () => {
    let finish: (value: { success: boolean }) => void = () => {};
    mocks.updateUserSettingsAction.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      })
    );
    const user = userEvent.setup();

    render(<SettingsPage />);
    await user.click(await screen.findByRole('button', { name: /save settings/i }));

    expect(await screen.findByRole('button', { name: /saving/i })).toBeDisabled();
    expect(mocks.toast).not.toHaveBeenCalled();

    finish({ success: true });

    expect(await screen.findByRole('button', { name: /save settings/i })).toBeEnabled();
    expect(mocks.toast).toHaveBeenCalledWith(
      expect.objectContaining({ description: expect.stringMatching(/settings updated/i) })
    );
    expect(mocks.updateUserSettingsAction).toHaveBeenCalledWith(SETTINGS);
  });

  it('shows a destructive toast when saving fails', async () => {
    mocks.updateUserSettingsAction.mockResolvedValue({ success: false, error: 'Nope' });
    const user = userEvent.setup();

    render(<SettingsPage />);
    await user.click(await screen.findByRole('button', { name: /save settings/i }));

    await waitFor(() =>
      expect(mocks.toast).toHaveBeenCalledWith(
        expect.objectContaining({ variant: 'destructive', description: 'Nope' })
      )
    );
  });
});

describe('SettingsPage reset', () => {
  it('restores the saved values after Reset', async () => {
    const user = userEvent.setup();

    render(<SettingsPage />);
    const language = await screen.findByRole('combobox', { name: 'Language' });
    expect(language).toHaveTextContent('Français');

    await user.click(screen.getByRole('switch', { name: 'Email Notifications' }));
    expect(screen.getByRole('switch', { name: 'Email Notifications' })).not.toBeChecked();

    await user.click(screen.getByRole('button', { name: /reset/i }));

    expect(screen.getByRole('switch', { name: 'Email Notifications' })).toBeChecked();
    expect(screen.getByRole('combobox', { name: 'Language' })).toHaveTextContent('Français');
  });
});
