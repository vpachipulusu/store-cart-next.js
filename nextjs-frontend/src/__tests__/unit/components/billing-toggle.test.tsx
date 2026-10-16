import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BillingToggle } from '@/components/pricing/billing-toggle';

/** KAN-225: billing toggle as an accessible radiogroup. */

const setup = (
  props: Partial<React.ComponentProps<typeof BillingToggle>> = {},
  onToggle = vi.fn()
) => {
  render(<BillingToggle billingPeriod="monthly" onToggle={onToggle} {...props} />);
  return {
    onToggle,
    monthly: screen.getByRole('radio', { name: /monthly/i }),
    yearly: screen.getByRole('radio', { name: /yearly/i }),
  };
};

describe('BillingToggle', () => {
  it('renders a named radiogroup with two radios', () => {
    setup();
    expect(screen.getByRole('radiogroup', { name: /billing period/i })).toBeInTheDocument();
    expect(screen.getAllByRole('radio')).toHaveLength(2);
  });

  it('marks only the active period as checked', () => {
    const { monthly, yearly } = setup({ billingPeriod: 'yearly' });
    expect(yearly).toHaveAttribute('aria-checked', 'true');
    expect(monthly).toHaveAttribute('aria-checked', 'false');
  });

  it('uses roving tabIndex', () => {
    const { monthly, yearly } = setup({ billingPeriod: 'yearly' });
    expect(yearly).toHaveAttribute('tabindex', '0');
    expect(monthly).toHaveAttribute('tabindex', '-1');
  });

  it('calls onToggle on click', async () => {
    const { onToggle, yearly } = setup();
    await userEvent.click(yearly);
    expect(onToggle).toHaveBeenCalledWith('yearly');
  });

  it.each(['{ArrowRight}', '{ArrowDown}', '{End}'])(
    '%s selects yearly from monthly',
    async (key) => {
      const { onToggle, monthly, yearly } = setup();
      monthly.focus();
      await userEvent.keyboard(key);
      expect(onToggle).toHaveBeenCalledWith('yearly');
      expect(yearly).toHaveFocus();
    }
  );

  it.each(['{ArrowLeft}', '{ArrowUp}', '{Home}'])('%s selects monthly from yearly', async (key) => {
    const { onToggle, monthly, yearly } = setup({ billingPeriod: 'yearly' });
    yearly.focus();
    await userEvent.keyboard(key);
    expect(onToggle).toHaveBeenCalledWith('monthly');
    expect(monthly).toHaveFocus();
  });

  it('wraps around with arrow keys', async () => {
    const { onToggle, monthly } = setup();
    monthly.focus();
    await userEvent.keyboard('{ArrowLeft}');
    expect(onToggle).toHaveBeenCalledWith('yearly');
  });

  it('ignores other keys', async () => {
    const { onToggle, monthly } = setup();
    monthly.focus();
    await userEvent.keyboard('a');
    expect(onToggle).not.toHaveBeenCalled();
  });

  it('sizes each option to at least 44px high and 96px wide', () => {
    const { monthly, yearly } = setup();
    for (const radio of [monthly, yearly]) {
      expect(radio.className).toContain('min-h-11');
      expect(radio.className).toContain('min-w-24');
    }
  });

  it('fills the selected option with foreground and background text, not the cta colour', () => {
    const { monthly, yearly } = setup();
    expect(monthly.className).toContain('bg-foreground');
    expect(monthly.className).toContain('text-background');
    expect(monthly.className).not.toContain('bg-cta');
    expect(yearly.className).not.toContain('bg-foreground');
  });

  it('respects reduced motion', () => {
    const { monthly } = setup();
    expect(monthly.className).toContain('motion-reduce:transition-none');
  });

  it('shows the saving as plain text inside the yearly option', () => {
    const { yearly } = setup({ yearlySavingsPercent: 17 });
    expect(yearly).toHaveTextContent('Save 17%');
  });

  it.each([undefined, 0, -5, Number.NaN])('hides the saving for %s', (value) => {
    setup({ yearlySavingsPercent: value });
    expect(screen.queryByText(/save/i)).not.toBeInTheDocument();
  });
});
