'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { fulfilOrderAction } from '@/app/actions/order-actions';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { fieldErrors } from '@/lib/products/schema';
import { fulfilOrderSchema, TRACKING_MAX_LENGTH } from '@/lib/orders/schema';
import { Field } from '../products/field';

/** Manual fulfilment of a paid order: a tracking number and an optional carrier. */
export function FulfilForm({ orderId }: { orderId: string }) {
  const router = useRouter();
  const [trackingNumber, setTrackingNumber] = useState('');
  const [carrier, setCarrier] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [failure, setFailure] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (pending) return;
    setFailure(null);
    const input = { trackingNumber, carrier };
    const parsed = fulfilOrderSchema.safeParse(input);
    if (!parsed.success) {
      setErrors(fieldErrors(parsed.error));
      setFailure('Check the highlighted fields and try again.');
      return;
    }
    setErrors({});
    setPending(true);
    let response: Awaited<ReturnType<typeof fulfilOrderAction>>;
    try {
      response = await fulfilOrderAction(orderId, input);
    } catch {
      setFailure('The request failed. Please try again.');
      return;
    } finally {
      setPending(false);
    }
    if (!response.success) {
      setErrors(response.fieldErrors ?? {});
      setFailure(response.error);
      return;
    }
    router.refresh();
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-4" aria-label="Fulfil order">
      {failure && (
        <Alert variant="destructive">
          <AlertDescription>{failure}</AlertDescription>
        </Alert>
      )}
      <Field id="fulfil-tracking" label="Tracking number" error={errors.trackingNumber}>
        {(describedBy) => (
          <Input
            id="fulfil-tracking"
            name="trackingNumber"
            value={trackingNumber}
            onChange={(event) => setTrackingNumber(event.target.value)}
            maxLength={TRACKING_MAX_LENGTH}
            required
            autoComplete="off"
            disabled={pending}
            aria-invalid={Boolean(errors.trackingNumber)}
            aria-describedby={describedBy}
          />
        )}
      </Field>
      <Field
        id="fulfil-carrier"
        label="Carrier (optional)"
        error={errors.carrier}
        hint="For example Royal Mail or UPS."
      >
        {(describedBy) => (
          <Input
            id="fulfil-carrier"
            name="carrier"
            value={carrier}
            onChange={(event) => setCarrier(event.target.value)}
            maxLength={TRACKING_MAX_LENGTH}
            autoComplete="off"
            disabled={pending}
            aria-invalid={Boolean(errors.carrier)}
            aria-describedby={describedBy}
          />
        )}
      </Field>
      <Button type="submit" disabled={pending}>
        {pending ? 'Marking as fulfilled…' : 'Mark as fulfilled'}
      </Button>
    </form>
  );
}
