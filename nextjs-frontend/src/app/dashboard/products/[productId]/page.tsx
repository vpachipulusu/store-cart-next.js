import Link from 'next/link';
import { notFound } from 'next/navigation';
import { ProductEditor } from '@/components/dashboard/products/product-editor';
import { ProductsLoadError } from '@/components/dashboard/products/products-load-error';
import { fetchProduct, loadCategoryList, productErrorMessage } from '@/lib/api/products';
import { isEntityId } from '@/lib/products/schema';
import { getCurrentStoreSelection } from '@/lib/stores/current';

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
        <ProductsLoadError
          message={productErrorMessage(result)}
          retryHref={`/dashboard/products/${productId}`}
        />
      )}
    </div>
  );
}
