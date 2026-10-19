import Link from 'next/link';
import { ProductCreateForm } from '@/components/dashboard/products/product-create-form';
import { ProductsLoadError } from '@/components/dashboard/products/products-load-error';
import { fetchProducts, loadCategoryList, productErrorMessage } from '@/lib/api/products';
import { getCurrentStoreSelection } from '@/lib/stores/current';
import { isStoreInSetup } from '@/lib/stores/provisioning';
import { StoreSetupState } from '@/components/dashboard/store-setup-state';

export const metadata = { title: 'New product' };

export default async function NewProductPage() {
  const selection = await getCurrentStoreSelection();
  if (!selection.available || !selection.selected) return null;
  if (isStoreInSetup(selection.selected.status)) {
    const { id, name, status } = selection.selected;
    return <StoreSetupState storeId={id} storeName={name} status={status} />;
  }

  // The list response is the only place the API reports the store currency before a product exists.
  const [result, categories] = await Promise.all([
    fetchProducts(selection.selected.id, { limit: 1 }),
    loadCategoryList(selection.selected.id),
  ]);

  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/dashboard/products"
          className="inline-flex min-h-11 items-center text-sm text-muted-foreground underline-offset-4 hover:underline"
        >
          Back to products
        </Link>
        <h1 className="text-3xl font-bold tracking-tight">New product</h1>
      </div>
      {result.success ? (
        <ProductCreateForm currency={result.data.currency} categories={categories} />
      ) : (
        <ProductsLoadError
          message={productErrorMessage(result)}
          retryHref="/dashboard/products/new"
        />
      )}
    </div>
  );
}
