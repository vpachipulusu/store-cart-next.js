'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';

/** A destructive action that needs a second click: the first shows Confirm and Cancel. */
export function ConfirmButton({
  label,
  confirmLabel,
  pending,
  onConfirm,
}: {
  label: string;
  confirmLabel: string;
  pending?: boolean;
  onConfirm: () => void;
}) {
  const [asking, setAsking] = useState(false);

  if (!asking) {
    return (
      <Button type="button" variant="outline" disabled={pending} onClick={() => setAsking(true)}>
        {label}
      </Button>
    );
  }
  return (
    <span className="inline-flex flex-wrap gap-2" role="group" aria-label={label}>
      <Button
        type="button"
        variant="destructive"
        disabled={pending}
        onClick={() => {
          setAsking(false);
          onConfirm();
        }}
      >
        {confirmLabel}
      </Button>
      <Button type="button" variant="outline" onClick={() => setAsking(false)}>
        Cancel
      </Button>
    </span>
  );
}
