'use client';

import { useState } from 'react';
import { deleteImageAction } from '@/app/actions/product-actions';
import { Alert, AlertDescription } from '@/components/ui/alert';
import type { ProductData } from '@/lib/api/products';
import { ConfirmButton } from './confirm-button';

/**
 * Images already attached to the product. Adding is not offered: it needs a browser upload to storage, which is
 * not decided yet, so only removal is available. The public image address is not known to the dashboard, so
 * each image shows by its alt text and storage key.
 */
export function ImagesPanel({
  product,
  onUpdated,
}: {
  product: ProductData;
  onUpdated: (product: ProductData) => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);

  async function remove(imageId: string) {
    setError(null);
    setPendingId(imageId);
    try {
      const response = await deleteImageAction(product.id, imageId);
      if (response.success) onUpdated(response.data);
      else setError(response.error);
    } catch {
      setError('The request failed. Please try again.');
    } finally {
      setPendingId(null);
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Uploading new images from the dashboard is not available yet. You can remove images that are
        already attached.
      </p>
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {product.images.length === 0 ? (
        <p data-testid="no-images" className="text-sm">
          This product has no images.
        </p>
      ) : (
        <ul className="divide-y rounded-lg border">
          {[...product.images]
            .sort((a, b) => a.position - b.position)
            .map((image) => (
              <li
                key={image.id}
                data-testid="image-row"
                className="flex flex-wrap items-center justify-between gap-3 p-3"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{image.alt_text ?? 'No alt text'}</p>
                  <code className="block truncate text-xs text-muted-foreground">
                    {image.storage_key}
                  </code>
                </div>
                <ConfirmButton
                  label={`Remove image ${image.position}`}
                  confirmLabel="Remove image"
                  pending={pendingId === image.id}
                  onConfirm={() => remove(image.id)}
                />
              </li>
            ))}
        </ul>
      )}
    </div>
  );
}
