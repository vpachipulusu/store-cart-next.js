import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { Skeleton } from '@/components/ui/skeleton';

/** KAN-214: a skeleton keeps its size and only animates when motion is allowed. */

describe('Skeleton', () => {
  it('is hidden from assistive technology', () => {
    const { container } = render(<Skeleton />);

    expect(container.firstElementChild).toHaveAttribute('aria-hidden', 'true');
  });

  it('keeps the size it is given', () => {
    const { container } = render(<Skeleton className="h-8 w-[120px]" />);

    expect(container.firstElementChild).toHaveClass('h-8', 'w-[120px]');
  });

  it('pulses only under motion-safe, so reduced motion shows a static block', () => {
    const { container } = render(<Skeleton />);
    const el = container.firstElementChild as HTMLElement;

    expect(el).toHaveClass('motion-safe:animate-pulse');
    expect(el.className).not.toMatch(/(^|\s)animate-pulse/);
  });

  it('uses a token fill, not a hard-coded colour', () => {
    const { container } = render(<Skeleton />);

    expect(container.firstElementChild).toHaveClass('bg-secondary');
  });

  it('forwards props such as data attributes', () => {
    const { container } = render(<Skeleton data-testid="s" />);

    expect(container.querySelector('[data-testid="s"]')).not.toBeNull();
  });
});
