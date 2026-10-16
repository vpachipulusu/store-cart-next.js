import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { StatusPill, type StatusPillVariant } from '@/components/ui/status-pill';

/** KAN-214: status is always icon + text + tint, never colour alone. */

const VARIANTS: Array<[StatusPillVariant, string, string]> = [
  ['good', 'bg-good', 'text-good-foreground'],
  ['warn', 'bg-warn', 'text-warn-foreground'],
  ['crit', 'bg-crit', 'text-crit-foreground'],
  ['info', 'bg-info', 'text-info-foreground'],
  ['neutral', 'bg-secondary', 'text-foreground'],
];

describe('StatusPill', () => {
  it.each(VARIANTS)('%s variant renders its tint and text pair', (variant, bg, fg) => {
    render(<StatusPill variant={variant}>Label</StatusPill>);

    const pill = screen.getByText('Label').closest('span');
    expect(pill).toHaveClass(bg, fg, 'rounded-full');
  });

  it.each(VARIANTS)('%s variant has a decorative icon alongside the text', (variant) => {
    const { container } = render(<StatusPill variant={variant}>Label</StatusPill>);

    const icon = container.querySelector('svg');
    expect(icon).not.toBeNull();
    expect(icon).toHaveAttribute('aria-hidden', 'true');
    expect(screen.getByText('Label')).toBeInTheDocument();
  });

  it('uses a different icon per variant so status is not colour-only', () => {
    const markup = VARIANTS.map(([variant]) => {
      const { container, unmount } = render(<StatusPill variant={variant}>x</StatusPill>);
      const html = container.querySelector('svg')?.innerHTML;
      unmount();
      return html;
    });

    expect(new Set(markup).size).toBe(VARIANTS.length);
  });

  it('exposes its text as the accessible name, not the icon', () => {
    render(<StatusPill variant="good">Paid</StatusPill>);

    expect(screen.getByText('Paid').closest('span')).toHaveTextContent(/^Paid$/);
  });

  it('defaults to the neutral variant', () => {
    render(<StatusPill>Draft</StatusPill>);

    expect(screen.getByText('Draft').closest('span')).toHaveClass('bg-secondary');
  });

  it('is a 24px pill with the documented type', () => {
    render(<StatusPill variant="info">New</StatusPill>);

    expect(screen.getByText('New').closest('span')).toHaveClass(
      'h-6',
      'text-[13px]',
      'font-semibold'
    );
  });

  it('merges a custom className and forwards props', () => {
    render(
      <StatusPill variant="warn" className="ml-2" data-testid="pill">
        Pending
      </StatusPill>
    );

    expect(screen.getByTestId('pill')).toHaveClass('ml-2', 'bg-warn');
  });
});
