import { ProductsLoadError } from '@/components/dashboard/products/products-load-error';
import {
  StoreSettingsForm,
  type StoreSettingsValues,
} from '@/components/dashboard/settings/store-settings-form';
import { fetchStoreSettings, storeSettingsErrorMessage } from '@/lib/api/store-settings';
import { fetchPlatformCurrency } from '@/lib/api/settings';
import { logger } from '@/lib/logger';
import { currencyExponent } from '@/lib/products/money';
import { getCurrentStoreSelection } from '@/lib/stores/current';

export const metadata = { title: 'Shipping and tax' };

const CURRENCY_UNAVAILABLE_MESSAGE = 'The store currency could not be read. Please try again.';

/** Null when the lookup fails: guessing a currency would misread amounts (JPY has no cents, KWD has three decimals). */
async function loadCurrency(): Promise<string | null> {
  try {
    return await fetchPlatformCurrency();
  } catch {
    return null;
  }
}

export default async function StoreSettingsPage() {
  // The layout already explains a missing store or a failed store list, so there is nothing to show here.
  const selection = await getCurrentStoreSelection();
  if (!selection.available || !selection.selected) return null;

  const [result, currency] = await Promise.all([
    fetchStoreSettings(selection.selected.id),
    loadCurrency(),
  ]);
  if (!result.success) {
    logger.error('Store settings page: load failed', { status: result.status });
  }

  const initial: StoreSettingsValues | null =
    result.success && currency !== null
      ? {
          shippingFlatRateMinor: result.data.shipping_flat_rate_minor,
          freeShippingThresholdMinor: result.data.free_shipping_threshold_minor,
          taxRateBps: result.data.tax_rate_bps,
          pricesIncludeTax: result.data.prices_include_tax,
        }
      : null;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl tracking-tight">Shipping and tax</h1>
        <p className="text-muted-foreground">
          How {selection.selected.name} charges for shipping and tax. Totals are worked out on the
          server from these settings.
        </p>
      </header>
      {initial && currency !== null ? (
        <StoreSettingsForm
          key={selection.selected.id}
          initial={initial}
          currency={currency}
          exponent={currencyExponent(currency)}
        />
      ) : (
        <ProductsLoadError
          message={
            result.success ? CURRENCY_UNAVAILABLE_MESSAGE : storeSettingsErrorMessage(result)
          }
          retryHref="/dashboard/settings/store"
        />
      )}
    </div>
  );
}
