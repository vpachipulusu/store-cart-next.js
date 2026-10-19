import Link from 'next/link';
import { notFound } from 'next/navigation';
import { ProductEditor } from '@/components/dashboard/products/product-editor';
import { ProductsLoadError } from '@/components/dashboard/products/products-load-error';
import { fetchProduct, loadCategoryList, productErrorMessage } from '@/lib/api/products';
import { isEntityId } from '@/lib/products/schema';
import { getCurrentStoreSelection } from '@/lib/stores/current';
import { isStoreInSetup } from '@/lib/stores/provisioning';
import { StoreSetupState } from '@/components/dashboard/store-setup-state';

export const metadata = { title: 'Edit product' };

export default async function EditProductPage({
  params,
}: {
  params: Promise<{ productId: string }>;
}) {
  const { productId } = await params;
  if (!isEntityId(productId)) notFound();

  const selection = await getCurrentStoreSelection();
  if (!selection.available || !selection.selected) return null;
  if (isStoreInSetup(selection.selected.status)) {
    const { id, name, status } = selection.selected;
    return <StoreSetupState storeId={id} storeName={name} status={status} />;
  }

  const [result, categories] = await Promise.all([
    fetchProduct(selection.selected.id, productId),
    loadCategoryList(selection.selected.id),
  ]);
  if (!result.success && result.status === 404) notFound();

  return (
    <div className="space-y-6">
      <Link
        href="/dashboard/products"
        className="inline-flex min-h-11 items-center text-sm text-muted-foreground underline-offset-4 hover:underline"
      >
        Back to products
      </Link>
      {result.success ? (
        <ProductEditor key={result.data.id} initial={result.data} categories={categories} />
      ) : (
        <>
          <h1 className="text-3xl font-bold tracking-tight">Product</h1>
          <ProductsLoadError
            message={productErrorMessage(result)}
            retryHref={`/dashboard/products/${productId}`}
          />
        </>
      )}
    </div>
  );
}
