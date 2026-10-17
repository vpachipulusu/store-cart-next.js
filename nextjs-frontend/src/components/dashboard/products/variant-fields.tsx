'use client';

import { Input } from '@/components/ui/input';
import type { VariantDraft } from '@/lib/products/draft';
import { Field } from './field';

/** The five variant inputs shared by the create form, the row editor and the add-variant form. */
export function VariantFields({
  idPrefix,
  draft,
  onChange,
  errors,
  currency,
  disabled,
}: {
  idPrefix: string;
  draft: VariantDraft;
  onChange: (next: VariantDraft) => void;
  errors: Record<string, string>;
  currency: string;
  disabled?: boolean;
}) {
  const set = (key: keyof VariantDraft) => (event: React.ChangeEvent<HTMLInputElement>) =>
    onChange({ ...draft, [key]: event.target.value });

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
      <Field id={`${idPrefix}-sku`} label="SKU" error={errors.sku}>
        {(describedBy) => (
          <Input
            id={`${idPrefix}-sku`}
            value={draft.sku}
            onChange={set('sku')}
            maxLength={100}
            disabled={disabled}
            aria-invalid={Boolean(errors.sku)}
            aria-describedby={describedBy}
          />
        )}
      </Field>
      <Field id={`${idPrefix}-price`} label={`Price (${currency})`} error={errors.price}>
        {(describedBy) => (
          <Input
            id={`${idPrefix}-price`}
            inputMode="decimal"
            value={draft.price}
            onChange={set('price')}
            disabled={disabled}
            aria-invalid={Boolean(errors.price)}
            aria-describedby={describedBy}
          />
        )}
      </Field>
      <Field id={`${idPrefix}-compare`} label={`Compare-at (${currency})`} error={errors.compareAt}>
        {(describedBy) => (
          <Input
            id={`${idPrefix}-compare`}
            inputMode="decimal"
            value={draft.compareAt}
            onChange={set('compareAt')}
            disabled={disabled}
            aria-invalid={Boolean(errors.compareAt)}
            aria-describedby={describedBy}
          />
        )}
      </Field>
      <Field id={`${idPrefix}-stock`} label="Stock" error={errors.stock}>
        {(describedBy) => (
          <Input
            id={`${idPrefix}-stock`}
            inputMode="numeric"
            value={draft.stock}
            onChange={set('stock')}
            disabled={disabled}
            aria-invalid={Boolean(errors.stock)}
            aria-describedby={describedBy}
          />
        )}
      </Field>
      <Field id={`${idPrefix}-weight`} label="Weight (g)" error={errors.weight}>
        {(describedBy) => (
          <Input
            id={`${idPrefix}-weight`}
            inputMode="numeric"
            value={draft.weight}
            onChange={set('weight')}
            disabled={disabled}
            aria-invalid={Boolean(errors.weight)}
            aria-describedby={describedBy}
          />
        )}
      </Field>
    </div>
  );
}
