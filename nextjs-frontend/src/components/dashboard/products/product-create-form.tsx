'use client';

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Plus, Trash2 } from 'lucide-react';
import { createProductAction } from '@/app/actions/product-actions';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { draftToVariant, EMPTY_VARIANT_DRAFT, type VariantDraft } from '@/lib/products/draft';
import { currencyExponent } from '@/lib/products/money';
import {
  createProductSchema,
  fieldErrors,
  indexedCombinations,
  MAX_OPTIONS,
  MAX_VARIANTS,
  type OptionInput,
  type VariantInput,
} from '@/lib/products/schema';
import type { CategoryList } from './categories-field';
import { DetailsFields, type DetailsDraft } from './details-fields';
import { Field } from './field';
import { VariantFields } from './variant-fields';

type OptionDraft = { name: string; values: string };

const INITIAL_DETAILS: DetailsDraft = {
  title: '',
  slug: '',
  description: '',
  status: 'draft',
  categoryIds: [],
};

function parseOptions(drafts: ReadonlyArray<OptionDraft>): OptionInput[] {
  return drafts
    .map((option) => ({
      name: option.name.trim(),
      values: [
        ...new Set(
          option.values
            .split(',')
            .map((value) => value.trim())
            .filter(Boolean)
        ),
      ],
    }))
    .filter((option) => option.name !== '' && option.values.length > 0);
}

function comboLabel(combo: Record<string, string>): string {
  const parts = Object.values(combo);
  return parts.length > 0 ? parts.join(' / ') : 'Default variant';
}

/** Create a product with its options and one variant per option combination (options cannot be edited later). */
export function ProductCreateForm({
  currency,
  categories,
}: {
  currency: string;
  categories: CategoryList | null;
}) {
  const router = useRouter();
  const exponent = currencyExponent(currency);
  const [details, setDetails] = useState<DetailsDraft>(INITIAL_DETAILS);
  const [optionDrafts, setOptionDrafts] = useState<ReadonlyArray<OptionDraft>>([]);
  const [rows, setRows] = useState<Record<string, VariantDraft>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [rowErrors, setRowErrors] = useState<Record<string, Record<string, string>>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [optionsError, setOptionsError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const options = useMemo(() => parseOptions(optionDrafts), [optionDrafts]);
  const combos = useMemo(() => indexedCombinations(options), [options]);
  const tooManyVariants = combos.length > MAX_VARIANTS;

  function updateOption(index: number, next: OptionDraft) {
    setOptionDrafts(optionDrafts.map((option, i) => (i === index ? next : option)));
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (pending) return;
    setFormError(null);
    setOptionsError(null);

    const half = optionDrafts.find(
      (option) => (option.name.trim() === '') !== (option.values.trim() === '')
    );
    const names = options.map((option) => option.name.toLowerCase());
    const problem = half
      ? 'Each option needs a name and at least one value. Fill in or remove the option.'
      : new Set(names).size !== names.length
        ? 'Each option needs a different name.'
        : tooManyVariants
          ? `These options make ${combos.length} variants; a product can have at most ${MAX_VARIANTS}.`
          : null;
    if (problem) {
      setOptionsError(problem);
      setFormError(problem);
      return;
    }

    const nextRowErrors: Record<string, Record<string, string>> = {};
    const variants: VariantInput[] = [];
    for (const { key, values } of combos) {
      const result = draftToVariant(
        rows[key] ?? EMPTY_VARIANT_DRAFT,
        exponent,
        options.length > 0 ? values : undefined
      );
      if (result.ok) variants.push(result.value);
      else nextRowErrors[key] = result.errors;
    }

    const parsed = createProductSchema.safeParse({ ...details, options, variants });
    const allErrors = parsed.success ? {} : fieldErrors(parsed.error);
    const { variants: variantsMessage, options: optionsMessage, ...topErrors } = allErrors;
    setOptionsError(optionsMessage ?? null);
    setRowErrors(nextRowErrors);
    setErrors(topErrors);
    if (
      !parsed.success ||
      Object.keys(nextRowErrors).length > 0 ||
      Object.keys(topErrors).length > 0 ||
      optionsMessage
    ) {
      setFormError(
        variantsMessage ?? optionsMessage ?? 'Check the highlighted fields and try again.'
      );
      return;
    }

    setPending(true);
    let response: Awaited<ReturnType<typeof createProductAction>>;
    try {
      response = await createProductAction(parsed.data);
    } catch {
      setPending(false);
      setFormError('The request failed. Please try again.');
      return;
    }
    if (response.success) {
      router.push(`/dashboard/products/${response.data.id}`);
      return;
    }
    setPending(false);
    setErrors(response.fieldErrors ?? {});
    setFormError(response.error);
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-8" aria-label="New product">
      {formError && (
        <Alert variant="destructive" role="alert">
          <AlertDescription>{formError}</AlertDescription>
        </Alert>
      )}

      <section aria-labelledby="details-heading" className="space-y-4">
        <h2 id="details-heading" className="text-xl font-semibold">
          Details
        </h2>
        <DetailsFields
          idPrefix="new"
          draft={details}
          onChange={setDetails}
          errors={errors}
          disabled={pending}
          categories={categories}
          slugHint="Optional. Lowercase letters, digits and hyphens. Made from the title when left empty."
        />
      </section>

      <section aria-labelledby="options-heading" className="space-y-4">
        <div>
          <h2 id="options-heading" className="text-xl font-semibold">
            Options
          </h2>
          <p className="text-sm text-muted-foreground">
            Optional, up to {MAX_OPTIONS} (for example Size). Options and their values cannot be
            changed after the product is created.
          </p>
          {optionsError && (
            <p role="alert" className="mt-1 text-sm text-destructive">
              {optionsError}
            </p>
          )}
        </div>
        {optionDrafts.map((option, index) => (
          <div key={index} className="flex flex-wrap items-end gap-3" data-testid="option-row">
            <Field id={`option-name-${index}`} label={`Option ${index + 1} name`}>
              {() => (
                <Input
                  id={`option-name-${index}`}
                  value={option.name}
                  maxLength={100}
                  onChange={(event) => updateOption(index, { ...option, name: event.target.value })}
                />
              )}
            </Field>
            <Field
              id={`option-values-${index}`}
              label={`Option ${index + 1} values`}
              hint="Separate values with commas."
            >
              {(describedBy) => (
                <Input
                  id={`option-values-${index}`}
                  value={option.values}
                  aria-describedby={describedBy}
                  onChange={(event) =>
                    updateOption(index, { ...option, values: event.target.value })
                  }
                />
              )}
            </Field>
            <Button
              type="button"
              variant="outline"
              size="icon"
              aria-label={`Remove option ${index + 1}`}
              onClick={() => setOptionDrafts(optionDrafts.filter((_, i) => i !== index))}
            >
              <Trash2 aria-hidden="true" />
            </Button>
          </div>
        ))}
        {optionDrafts.length < MAX_OPTIONS && (
          <Button
            type="button"
            variant="outline"
            onClick={() => setOptionDrafts([...optionDrafts, { name: '', values: '' }])}
          >
            <Plus aria-hidden="true" />
            Add option
          </Button>
        )}
      </section>

      <section aria-labelledby="variants-heading" className="space-y-4">
        <h2 id="variants-heading" className="text-xl font-semibold">
          Variants
        </h2>
        <p className="text-sm text-muted-foreground">
          Prices are in {currency}. Leave compare-at empty for no sale price.
        </p>
        {tooManyVariants && (
          <p role="alert" className="text-sm text-destructive">
            These options make {combos.length} variants; a product can have at most {MAX_VARIANTS}.
            Remove an option or some values.
          </p>
        )}
        {(tooManyVariants ? [] : combos).map(({ key, values }, index) => {
          return (
            <fieldset
              key={key}
              className="space-y-2 rounded-lg border border-border p-4"
              data-testid="variant-row"
            >
              <legend className="px-1 text-sm font-medium">{comboLabel(values)}</legend>
              <VariantFields
                idPrefix={`variant-${index}`}
                draft={rows[key] ?? EMPTY_VARIANT_DRAFT}
                onChange={(next) => setRows({ ...rows, [key]: next })}
                errors={rowErrors[key] ?? {}}
                currency={currency}
                disabled={pending}
              />
            </fieldset>
          );
        })}
      </section>

      <div className="flex gap-3">
        <Button type="submit" disabled={pending}>
          {pending ? 'Creating…' : 'Create product'}
        </Button>
        <Button type="button" variant="outline" onClick={() => router.push('/dashboard/products')}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
