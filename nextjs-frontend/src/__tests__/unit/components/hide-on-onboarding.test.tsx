/** KAN-60: the "no store yet" notice must not render on the onboarding pages themselves. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

const mocks = vi.hoisted(() => ({ usePathname: vi.fn() }));
vi.mock('next/navigation', () => ({ usePathname: mocks.usePathname }));

import { HideOnOnboarding } from '@/components/dashboard/hide-on-onboarding';

const renderNotice = () =>
  render(
    <HideOnOnboarding>
      <div data-testid="no-stores">You do not have a store yet.</div>
    </HideOnOnboarding>
  );

describe('HideOnOnboarding', () => {
  beforeEach(() => vi.clearAllMocks());

  it.each(['/dashboard', '/dashboard/profile', '/dashboard/settings/billing'])(
    'shows its children on %s',
    (path) => {
      mocks.usePathname.mockReturnValue(path);
      renderNotice();
      expect(screen.getByTestId('no-stores')).toHaveTextContent('You do not have a store yet.');
    }
  );

  it.each(['/dashboard/onboarding', '/dashboard/onboarding/status/tz4a98xxat96iws9zmbrgj3a'])(
    'hides its children on %s',
    (path) => {
      mocks.usePathname.mockReturnValue(path);
      renderNotice();
      expect(screen.queryByTestId('no-stores')).toBeNull();
    }
  );

  it('does not hide on a look-alike path', () => {
    mocks.usePathname.mockReturnValue('/dashboard/onboarding-help');
    renderNotice();
    expect(screen.getByTestId('no-stores')).toBeInTheDocument();
  });
});
