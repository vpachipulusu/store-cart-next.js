'use client';

import { useState } from 'react';
import {
  addVariantAction,
  deleteVariantAction,
  updateVariantAction,
} from '@/app/actions/product-actions';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  draftToVariant,
  EMPTY_VARIANT_DRAFT,
  variantToDraft,
  type VariantDraft,
} from '@/lib/products/draft';
import { currencyExponent } from '@/lib/products/money';
import type { ProductData } from '@/lib/api/products';
import { ConfirmButton } from './confirm-button';
import { VariantFields } from './variant-fields';

type Variant = ProductData['variants'][number];

/** "Medium / Red" for a variant, from the product option names and value ids. */
export function variantLabel(product: ProductData, variant: Variant): string {
  const names = variant.option_values.flatMap((choice) => {
    const option = product.options.find((candidate) => candidate.id === choice.option_id);
    const value = option?.values.find((candidate) => candidate.id === choice.option_value_id);
    return value ? [value.value] : [];
  });
  return names.length > 0 ? names.join(' / ') : 'Default variant';
}

type PanelProps = {
  product: ProductData;
  onUpdated: (product: ProductData) => void;
};

function VariantRow({
  product,
  variant,
  exponent,
  onUpdated,
}: PanelProps & { variant: Variant; exponent: number }) {
  const [draft, setDraft] = useState<VariantDraft>(() => variantToDraft(variant, exponent));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<{ kind: 'error' | 'saved'; text: string } | null>(null);
  const [pending, setPending] = useState(false);

  async function save() {
    setMessage(null);
    const result = draftToVariant(draft, exponent);
    if (!result.ok) {
      setErrors(result.errors);
      return;
    }
    setErrors({});
    setPending(true);
    let response: Awaited<ReturnType<typeof updateVariantAction>>;
    try {
      response = await updateVariantAction(product.id, variant.id, result.value);
    } catch {
      setMessage({ kind: 'error', text: 'The request failed. Please try again.' });
      return;
    } finally {
      setPending(false);
    }
    if (response.success) {
      onUpdated(response.data);
      const saved = response.data.variants.find((candidate) => candidate.id === variant.id);
      if (saved) setDraft(variantToDraft(saved, exponent));
      setMessage({ kind: 'saved', text: 'Variant saved.' });
    } else {
      setMessage({ kind: 'error', text: response.error });
    }
  }

  async function remove() {
    setMessage(null);
    setPending(true);
    let response: Awaited<ReturnType<typeof deleteVariantAction>>;
    try {
      response = await deleteVariantAction(product.id, variant.id);
    } catch {
      setMessage({ kind: 'error', text: 'The request failed. Please try again.' });
      return;
    } finally {
      setPending(false);
    }
    if (response.success) onUpdated(response.data);
    else setMessage({ kind: 'error', text: response.error });
  }

  return (
    <fieldset className="space-y-3 rounded-lg border border-border p-4" data-testid="variant-row">
      <legend className="px-1 text-sm font-medium">{variantLabel(product, variant)}</legend>
      <VariantFields
        idPrefix={`variant-${variant.id}`}
        draft={draft}
        onChange={setDraft}
        errors={errors}
        currency={product.currency}
        disabled={pending}
      />
      {message?.kind === 'error' && (
        <Alert variant="destructive">
          <AlertDescription>{message.text}</AlertDescription>
        </Alert>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" onClick={save} disabled={pending}>
          Save variant
        </Button>
        <ConfirmButton
          label="Delete variant"
          confirmLabel="Confirm delete variant"
          pending={pending}
          onConfirm={remove}
        />
        {message?.kind === 'saved' && (
          <p role="status" className="text-sm text-muted-foreground">
            {message.text}
          </p>
        )}
      </div>
    </fieldset>
  );
}

function AddVariantForm({ product, exponent, onUpdated }: PanelProps & { exponent: number }) {
  const [draft, setDraft] = useState<VariantDraft>(EMPTY_VARIANT_DRAFT);
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (pending) return;
    setError(null);
    const missing = product.options.find((option) => !chosen[option.name]);
    if (missing) return setError(`Choose a value for ${missing.name}.`);
    const result = draftToVariant(draft, exponent, chosen);
    if (!result.ok) return setErrors(result.errors);
    setErrors({});
    setPending(true);
    let response: Awaited<ReturnType<typeof addVariantAction>>;
    try {
      response = await addVariantAction(product.id, result.value);
    } catch {
      setError('The request failed. Please try again.');
      return;
    } finally {
      setPending(false);
    }
    if (response.success) {
      onUpdated(response.data);
      setDraft(EMPTY_VARIANT_DRAFT);
      setChosen({});
    } else {
      setError(response.error);
    }
  }

  return (
    <form
      onSubmit={submit}
      noValidate
      aria-label="Add variant"
      className="space-y-3 rounded-lg border border-dashed p-4"
    >
      <h3 className="text-sm font-medium">Add a variant</h3>
      <div className="flex flex-wrap gap-3">
        {product.options.map((option) => (
          <div key={option.id} className="space-y-1.5">
            <label htmlFor={`add-option-${option.id}`} className="text-sm font-medium">
              {option.name}
            </label>
            <select
              id={`add-option-${option.id}`}
              value={chosen[option.name] ?? ''}
              onChange={(event) => setChosen({ ...chosen, [option.name]: event.target.value })}
              disabled={pending}
              className="block h-11 rounded-md border border-input bg-background px-3 text-sm"
            >
              <option value="">Choose…</option>
              {option.values.map((value) => (
                <option key={value.id} value={value.value}>
                  {value.value}
                </option>
              ))}
            </select>
          </div>
        ))}
      </div>
      <VariantFields
        idPrefix="add-variant"
        draft={draft}
        onChange={setDraft}
        errors={errors}
        currency={product.currency}
        disabled={pending}
      />
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <Button type="submit" disabled={pending}>
        {pending ? 'Adding…' : 'Add variant'}
      </Button>
    </form>
  );
}

/** Variants of the product, each editable in place. New variants need options, which are set at creation. */
export function VariantsPanel({ product, onUpdated }: PanelProps) {
  const exponent = currencyExponent(product.currency);
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Prices are in {product.currency}. A product always keeps at least one variant.
      </p>
      {product.variants.map((variant) => (
        <VariantRow
          key={variant.id}
          product={product}
          variant={variant}
          exponent={exponent}
          onUpdated={onUpdated}
        />
      ))}
      {product.options.length > 0 ? (
        <AddVariantForm product={product} exponent={exponent} onUpdated={onUpdated} />
      ) : (
        <p className="text-sm text-muted-foreground" data-testid="no-add-variant">
          This product has no options, so it has a single variant. Options are set when a product is
          created.
        </p>
      )}
    </div>
  );
}
