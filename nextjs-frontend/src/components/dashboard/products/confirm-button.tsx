'use client';

import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';

/**
 * A destructive action that needs a second click: the first shows Confirm and Cancel. Focus moves to Confirm when
 * asking starts and back to the trigger on Cancel or Escape. `ariaLabel` names the trigger and `confirmAriaLabel`
 * the Confirm button when several of these sit on one page.
 */
export function ConfirmButton({
  label,
  confirmLabel,
  ariaLabel,
  confirmAriaLabel,
  pending,
  onConfirm,
}: {
  label: string;
  confirmLabel: string;
  ariaLabel?: string;
  confirmAriaLabel?: string;
  pending?: boolean;
  onConfirm: () => void;
}) {
  const [asking, setAsking] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef(false);

  useEffect(() => {
    if (asking) {
      confirmRef.current?.focus();
    } else if (restoreFocus.current) {
      restoreFocus.current = false;
      triggerRef.current?.focus();
    }
  }, [asking]);

  function cancel() {
    restoreFocus.current = true;
    setAsking(false);
  }

  if (!asking) {
    return (
      <Button
        ref={triggerRef}
        type="button"
        variant="outline"
        aria-label={ariaLabel}
        disabled={pending}
        onClick={() => setAsking(true)}
      >
        {label}
      </Button>
    );
  }
  return (
    <span
      className="inline-flex flex-wrap gap-2"
      role="group"
      aria-label={ariaLabel ?? label}
      onKeyDown={(event) => {
        if (event.key === 'Escape') cancel();
      }}
    >
      <Button
        ref={confirmRef}
        type="button"
        variant="destructive"
        aria-label={confirmAriaLabel}
        disabled={pending}
        onClick={() => {
          setAsking(false);
          onConfirm();
        }}
      >
        {confirmLabel}
      </Button>
      <Button type="button" variant="outline" onClick={cancel}>
        Cancel
      </Button>
    </span>
  );
}
