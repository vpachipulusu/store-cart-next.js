'use client';

import { useState } from 'react';
import { updateProductAction } from '@/app/actions/product-actions';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { productDetailsSchema, fieldErrors } from '@/lib/products/schema';
import type { ProductData } from '@/lib/api/products';
import { DetailsFields, type DetailsDraft } from './details-fields';

function toDraft(product: ProductData): DetailsDraft {
  return {
    title: product.title,
    slug: product.slug,
    description: product.description ?? '',
    status: product.status,
    categoryIds: product.category_ids,
  };
}

/** Product-level fields of the editor. Saving replaces the whole category set, as the API does. */
export function ProductDetailsForm({
  product,
  onUpdated,
}: {
  product: ProductData;
  onUpdated: (product: ProductData) => void;
}) {
  const [draft, setDraft] = useState<DetailsDraft>(() => toDraft(product));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<{ kind: 'error' | 'saved'; text: string } | null>(null);
  const [pending, setPending] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (pending) return;
    setMessage(null);
    const parsed = productDetailsSchema.safeParse(draft);
    if (!parsed.success) {
      setErrors(fieldErrors(parsed.error));
      setMessage({ kind: 'error', text: 'Check the highlighted fields and try again.' });
      return;
    }
    setErrors({});
    setPending(true);
    let response: Awaited<ReturnType<typeof updateProductAction>>;
    try {
      response = await updateProductAction(product.id, parsed.data);
    } catch {
      setMessage({ kind: 'error', text: 'The request failed. Please try again.' });
      return;
    } finally {
      setPending(false);
    }
    if (!response.success) {
      setErrors(response.fieldErrors ?? {});
      setMessage({ kind: 'error', text: response.error });
      return;
    }
    onUpdated(response.data);
    setDraft(toDraft(response.data));
    setMessage({ kind: 'saved', text: 'Product saved.' });
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-4" aria-label="Product details">
      {message?.kind === 'error' && (
        <Alert variant="destructive">
          <AlertDescription>{message.text}</AlertDescription>
        </Alert>
      )}
      <DetailsFields
        idPrefix="edit"
        draft={draft}
        onChange={setDraft}
        errors={errors}
        disabled={pending}
        slugHint="Lowercase letters, digits and hyphens. Changing it changes the product address. Clearing it keeps the current one."
      />
      <div className="flex items-center gap-3">
        <Button type="submit" disabled={pending}>
          {pending ? 'Saving…' : 'Save details'}
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
