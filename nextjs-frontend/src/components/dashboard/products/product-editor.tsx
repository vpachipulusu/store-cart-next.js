'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { deleteProductAction } from '@/app/actions/product-actions';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import type { ProductData } from '@/lib/api/products';
import type { CategoryList } from './categories-field';
import { ConfirmButton } from './confirm-button';
import { ImagesPanel } from './images-panel';
import { ProductDetailsForm } from './product-details-form';
import { ProductStatusPill } from './product-status-pill';
import { VariantsPanel } from './variants-panel';

/** The product editor: details, variants, images and deletion. Each panel hands back the updated product. */
export function ProductEditor({
  initial,
  categories,
}: {
  initial: ProductData;
  categories: CategoryList | null;
}) {
  const router = useRouter();
  const [product, setProduct] = useState(initial);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  async function remove() {
    setDeleteError(null);
    setDeleting(true);
    try {
      const response = await deleteProductAction(product.id);
      if (response.success) {
        router.push('/dashboard/products');
        return;
      }
      setDeleteError(response.error);
    } catch {
      setDeleteError('The request failed. Please try again.');
    }
    setDeleting(false);
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-3xl font-bold tracking-tight">{product.title}</h1>
        <ProductStatusPill status={product.status} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Details</CardTitle>
          <CardDescription>Title, address, description, status and categories</CardDescription>
        </CardHeader>
        <CardContent>
          <ProductDetailsForm product={product} onUpdated={setProduct} categories={categories} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Variants</CardTitle>
          <CardDescription>SKU, price, stock and weight for each variant</CardDescription>
        </CardHeader>
        <CardContent>
          <VariantsPanel product={product} onUpdated={setProduct} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Images</CardTitle>
          <CardDescription>Images attached to this product</CardDescription>
        </CardHeader>
        <CardContent>
          <ImagesPanel product={product} onUpdated={setProduct} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Delete product</CardTitle>
          <CardDescription>
            Removes the product with its variants, images and category links. Past orders keep their
            snapshot.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {deleteError && (
            <Alert variant="destructive">
              <AlertDescription>{deleteError}</AlertDescription>
            </Alert>
          )}
          <ConfirmButton
            label="Delete product"
            confirmLabel="Confirm delete product"
            pending={deleting}
            onConfirm={remove}
          />
        </CardContent>
      </Card>
    </div>
  );
}
