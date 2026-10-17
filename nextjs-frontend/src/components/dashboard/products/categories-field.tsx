'use client';

import { useState } from 'react';
import { X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { isEntityId, MAX_CATEGORIES } from '@/lib/products/schema';

/**
 * Category links by id. The API has no endpoint to list or create categories yet, so a merchant can only keep,
 * remove or add ids they already know; the backend rejects an id that is not a category of this store.
 */
export function CategoriesField({
  value,
  onChange,
  error,
}: {
  value: ReadonlyArray<string>;
  onChange: (next: ReadonlyArray<string>) => void;
  error?: string;
}) {
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
        Category names are not available yet, so categories show by id. Add an id you already have,
        or remove one to unlink it.
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
