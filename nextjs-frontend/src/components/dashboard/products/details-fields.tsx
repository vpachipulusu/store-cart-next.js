'use client';

import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { SLUG_MAX_LENGTH, TITLE_MAX_LENGTH, type ProductStatus } from '@/lib/products/schema';
import { CategoriesField, type CategoryList } from './categories-field';
import { Field } from './field';

export type DetailsDraft = {
  title: string;
  slug: string;
  description: string;
  status: ProductStatus;
  categoryIds: ReadonlyArray<string>;
};

/** Title, slug, description, status and categories: the product-level fields of both forms. */
export function DetailsFields({
  idPrefix,
  draft,
  onChange,
  errors,
  disabled,
  slugHint,
  categories,
}: {
  idPrefix: string;
  draft: DetailsDraft;
  onChange: (next: DetailsDraft) => void;
  errors: Record<string, string>;
  disabled?: boolean;
  slugHint: string;
  categories: CategoryList | null;
}) {
  return (
    <div className="space-y-4">
      <Field id={`${idPrefix}-title`} label="Title" error={errors.title}>
        {(describedBy) => (
          <Input
            id={`${idPrefix}-title`}
            value={draft.title}
            onChange={(event) => onChange({ ...draft, title: event.target.value })}
            maxLength={TITLE_MAX_LENGTH}
            disabled={disabled}
            aria-invalid={Boolean(errors.title)}
            aria-describedby={describedBy}
          />
        )}
      </Field>
      <Field id={`${idPrefix}-slug`} label="Slug" hint={slugHint} error={errors.slug}>
        {(describedBy) => (
          <Input
            id={`${idPrefix}-slug`}
            value={draft.slug}
            onChange={(event) => onChange({ ...draft, slug: event.target.value })}
            maxLength={SLUG_MAX_LENGTH}
            disabled={disabled}
            aria-invalid={Boolean(errors.slug)}
            aria-describedby={describedBy}
          />
        )}
      </Field>
      <Field id={`${idPrefix}-description`} label="Description" error={errors.description}>
        {(describedBy) => (
          <Textarea
            id={`${idPrefix}-description`}
            value={draft.description}
            onChange={(event) => onChange({ ...draft, description: event.target.value })}
            rows={5}
            disabled={disabled}
            aria-invalid={Boolean(errors.description)}
            aria-describedby={describedBy}
          />
        )}
      </Field>
      <Field
        id={`${idPrefix}-status`}
        label="Status"
        hint="Draft products are not published. There is no archived status; unpublish by setting Draft."
      >
        {(describedBy) => (
          <select
            id={`${idPrefix}-status`}
            value={draft.status}
            onChange={(event) =>
              onChange({ ...draft, status: event.target.value === 'active' ? 'active' : 'draft' })
            }
            disabled={disabled}
            aria-describedby={describedBy}
            className="h-11 rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          >
            <option value="draft">Draft</option>
            <option value="active">Active</option>
          </select>
        )}
      </Field>
      <CategoriesField
        value={draft.categoryIds}
        onChange={(categoryIds) => onChange({ ...draft, categoryIds })}
        error={errors.categoryIds}
        categories={categories}
      />
    </div>
  );
}
