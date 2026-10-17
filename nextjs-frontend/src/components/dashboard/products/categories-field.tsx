'use client';

import { useMemo, useState } from 'react';
import { X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  toCategoryOptions,
  type CategoryList,
  type CategoryOption,
} from '@/lib/products/categories';
import { isEntityId, MAX_CATEGORIES } from '@/lib/products/schema';

export type { CategoryList };

type FieldProps = {
  value: ReadonlyArray<string>;
  onChange: (next: ReadonlyArray<string>) => void;
  error?: string;
  /** The store's categories, or null when they could not be loaded (the id field is shown instead). */
  categories: CategoryList | null;
};

/** Category links. With the store's category list it is a checkbox tree by name; without it, ids only. */
export function CategoriesField({ categories, ...props }: FieldProps) {
  return categories ? (
    <CategoryChecklist categories={categories} {...props} />
  ) : (
    <CategoryIdField {...props} />
  );
}

function CategoryChecklist({
  categories,
  value,
  onChange,
  error,
}: FieldProps & { categories: CategoryList }) {
  const options = useMemo(
    () => toCategoryOptions(categories.rows, categories.truncated),
    [categories]
  );
  const known = new Set(options.map((option) => option.id));
  // A linked id that is not in the list (a deleted category, or one past a truncated list) stays removable.
  const unknown = value.filter((id) => !known.has(id));
  const limitReached = value.length >= MAX_CATEGORIES;

  function toggle(id: string, checked: boolean) {
    onChange(checked ? [...value, id] : value.filter((existing) => existing !== id));
  }

  return (
    <fieldset className="space-y-2" data-testid="categories-field">
      <legend className="text-sm font-medium">Categories</legend>
      {categories.truncated && (
        <p className="text-xs text-muted-foreground">
          This store has more categories than can be shown, so only some are listed.
        </p>
      )}
      {options.length === 0 && unknown.length === 0 && (
        <p className="text-sm text-muted-foreground">This store has no categories yet.</p>
      )}
      <ul className="space-y-1">
        {options.map((option) => (
          <CategoryItem
            key={option.id}
            option={option}
            checked={value.includes(option.id)}
            disabled={limitReached && !value.includes(option.id)}
            onToggle={toggle}
          />
        ))}
        {unknown.map((id) => (
          <CategoryItem
            key={id}
            option={{ id, label: `Unknown category (${id})`, depth: 0 }}
            checked
            disabled={false}
            onToggle={toggle}
          />
        ))}
      </ul>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </fieldset>
  );
}

function CategoryItem({
  option,
  checked,
  disabled,
  onToggle,
}: {
  option: CategoryOption;
  checked: boolean;
  disabled: boolean;
  onToggle: (id: string, checked: boolean) => void;
}) {
  const id = `category-${option.id}`;
  return (
    <li style={{ paddingInlineStart: `${option.depth * 1.5}rem` }}>
      <label htmlFor={id} className="flex min-h-11 cursor-pointer items-center gap-2 text-sm">
        <input
          id={id}
          type="checkbox"
          className="size-5"
          checked={checked}
          disabled={disabled}
          onChange={(event) => onToggle(option.id, event.target.checked)}
        />
        {option.label}
      </label>
    </li>
  );
}

/** Fallback when the category list could not be loaded: ids the merchant already has. */
function CategoryIdField({ value, onChange, error }: Omit<FieldProps, 'categories'>) {
  const [draft, setDraft] = useState('');
  const [localError, setLocalError] = useState<string | undefined>();

  function add() {
    const id = draft.trim();
    if (!isEntityId(id)) return setLocalError('Enter a valid category id');
    if (value.includes(id)) return setLocalError('That category is already added');
    if (value.length >= MAX_CATEGORIES)
      return setLocalError(`At most ${MAX_CATEGORIES} categories`);
    onChange([...value, id]);
    setDraft('');
    setLocalError(undefined);
  }

  const shownError = localError ?? error;

  return (
    <fieldset className="space-y-2" data-testid="categories-field">
      <legend className="text-sm font-medium">Categories</legend>
      <p className="text-xs text-muted-foreground">
        Category names could not be loaded, so categories show by id. Reload the page to try again,
        or add an id you already have.
      </p>
      {value.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {value.map((id) => (
            <li
              key={id}
              className="inline-flex min-h-8 items-center gap-1 rounded-full bg-secondary pe-1 ps-3 text-sm"
            >
              <code>{id}</code>
              <button
                type="button"
                aria-label={`Remove category ${id}`}
                className="inline-flex size-11 items-center justify-center rounded-full hover:bg-background"
                onClick={() => {
                  setLocalError(undefined);
                  onChange(value.filter((existing) => existing !== id));
                }}
              >
                <X aria-hidden="true" className="size-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Input
          aria-label="Category id"
          value={draft}
          onChange={(event) => {
            setDraft(event.target.value);
            setLocalError(undefined);
          }}
          onKeyDown={(event) => {
            // Enter adds the category; it must not submit the surrounding product form.
            if (event.key === 'Enter') {
              event.preventDefault();
              add();
            }
          }}
          maxLength={64}
          className="max-w-xs"
          aria-invalid={Boolean(shownError)}
        />
        <Button type="button" variant="outline" onClick={add}>
          Add category
        </Button>
      </div>
      {shownError && (
        <p role="alert" className="text-sm text-destructive">
          {shownError}
        </p>
      )}
    </fieldset>
  );
}
