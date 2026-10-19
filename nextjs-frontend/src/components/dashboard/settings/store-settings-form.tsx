'use client';

import { useState } from 'react';
import { updateStoreSettingsAction } from '@/app/actions/store-settings-actions';
import { Field } from '@/components/dashboard/products/field';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { minorToInput } from '@/lib/products/money';
import { bpsToPercentInput, parseDraft, type StoreSettingsDraft } from '@/lib/store-settings/form';

export type StoreSettingsValues = {
  shippingFlatRateMinor: number;
  freeShippingThresholdMinor: number | null;
  taxRateBps: number;
  pricesIncludeTax: boolean;
};

function toDraft(values: StoreSettingsValues, exponent: number): StoreSettingsDraft {
  return {
    shippingFlatRate: minorToInput(values.shippingFlatRateMinor, exponent),
    freeShippingThreshold:
      values.freeShippingThresholdMinor === null
        ? ''
        : minorToInput(values.freeShippingThresholdMinor, exponent),
    taxRatePercent: bpsToPercentInput(values.taxRateBps),
    pricesIncludeTax: values.pricesIncludeTax,
  };
}

/**
 * Shipping and tax of the selected store (KAN-82, KAN-83). Amounts are typed in the store currency's major units
 * and the tax rate as a percentage; the server action receives minor units and basis points.
 */
export function StoreSettingsForm({
  initial,
  currency,
  exponent,
}: {
  initial: StoreSettingsValues;
  currency: string;
  exponent: number;
}) {
  const [draft, setDraft] = useState<StoreSettingsDraft>(() => toDraft(initial, exponent));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<{ kind: 'error' | 'saved'; text: string } | null>(null);
  const [pending, setPending] = useState(false);

  function change(patch: Partial<StoreSettingsDraft>) {
    setDraft((current) => ({ ...current, ...patch }));
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (pending) return;
    setMessage(null);
    const parsed = parseDraft(draft, exponent);
    if (!parsed.ok) {
      setErrors(parsed.errors);
      setMessage({ kind: 'error', text: 'Check the highlighted fields and try again.' });
      return;
    }
    setErrors({});
    setPending(true);
    let response: Awaited<ReturnType<typeof updateStoreSettingsAction>>;
    try {
      response = await updateStoreSettingsAction(parsed.value);
    } catch {
      setMessage({ kind: 'error', text: 'The request failed. Please try again.' });
      return;
    } finally {
      setPending(false);
    }
    if (!response.success) {
      setMessage({ kind: 'error', text: response.error });
      return;
    }
    setDraft(
      toDraft(
        {
          shippingFlatRateMinor: response.data.shipping_flat_rate_minor,
          freeShippingThresholdMinor: response.data.free_shipping_threshold_minor,
          taxRateBps: response.data.tax_rate_bps,
          pricesIncludeTax: response.data.prices_include_tax,
        },
        exponent
      )
    );
    setMessage({ kind: 'saved', text: 'Settings saved.' });
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-6" aria-label="Shipping and tax settings">
      {message?.kind === 'error' && (
        <Alert variant="destructive">
          <AlertDescription>{message.text}</AlertDescription>
        </Alert>
      )}

      <fieldset className="space-y-4 rounded-xl border border-border bg-card p-4">
        <legend className="px-1 text-lg">Shipping</legend>
        <Field
          id="shipping-flat-rate"
          label={`Flat shipping rate (${currency})`}
          error={errors.shippingFlatRate}
          hint="Charged once per order. Use 0 for free shipping."
        >
          {(describedBy) => (
            <Input
              id="shipping-flat-rate"
              inputMode="decimal"
              value={draft.shippingFlatRate}
              onChange={(event) => change({ shippingFlatRate: event.target.value })}
              aria-invalid={Boolean(errors.shippingFlatRate)}
              aria-describedby={describedBy}
              disabled={pending}
            />
          )}
        </Field>
        <Field
          id="free-shipping-threshold"
          label={`Free shipping over (${currency}, optional)`}
          error={errors.freeShippingThreshold}
          hint="Orders whose items add up to this amount or more ship free. Leave empty to always charge the flat rate."
        >
          {(describedBy) => (
            <Input
              id="free-shipping-threshold"
              inputMode="decimal"
              value={draft.freeShippingThreshold}
              onChange={(event) => change({ freeShippingThreshold: event.target.value })}
              aria-invalid={Boolean(errors.freeShippingThreshold)}
              aria-describedby={describedBy}
              disabled={pending}
            />
          )}
        </Field>
      </fieldset>

      <fieldset className="space-y-4 rounded-xl border border-border bg-card p-4">
        <legend className="px-1 text-lg">Tax</legend>
        <Field
          id="tax-rate"
          label="Tax rate (%)"
          error={errors.taxRatePercent}
          hint="For example 20 or 7.5. Applied to items, not to shipping."
        >
          {(describedBy) => (
            <Input
              id="tax-rate"
              inputMode="decimal"
              value={draft.taxRatePercent}
              onChange={(event) => change({ taxRatePercent: event.target.value })}
              aria-invalid={Boolean(errors.taxRatePercent)}
              aria-describedby={describedBy}
              disabled={pending}
            />
          )}
        </Field>
        <div className="flex items-center justify-between gap-4 rounded-lg border p-4">
          <div className="min-w-0 space-y-0.5">
            <label htmlFor="prices-include-tax" className="text-base font-medium">
              Prices include tax
            </label>
            <p id="prices-include-tax-hint" className="text-sm text-muted-foreground">
              Turn on if the prices you enter already contain tax. Turn off to add tax on top at
              checkout.
            </p>
          </div>
          <Switch
            id="prices-include-tax"
            checked={draft.pricesIncludeTax}
            onCheckedChange={(checked) => change({ pricesIncludeTax: checked })}
            aria-describedby="prices-include-tax-hint"
            disabled={pending}
            className="relative before:absolute before:-inset-2.5 before:content-['']"
          />
        </div>
      </fieldset>

      <div className="flex items-center gap-3">
        <Button type="submit" disabled={pending}>
          {pending ? 'Saving…' : 'Save settings'}
        </Button>
        {message?.kind === 'saved' && (
          <p role="status" className="text-sm text-muted-foreground">
            {message.text}
          </p>
        )}
      </div>
    </form>
  );
}
