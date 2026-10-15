import { notFound } from 'next/navigation';
import { fetchStoreStatus } from '@/lib/api/onboarding';
import { isStoreId } from '@/lib/stores/selection';
import { ProvisioningStatus } from '@/components/onboarding/provisioning-status';
import { Card, CardContent, CardDescription, CardHeader } from '@/components/ui/card';

export const metadata = {
  title: 'Store setup',
  description: 'Follow your store setup',
};

type StatusPageProps = { params: Promise<{ storeId: string }> };

/**
 * Store setup status (KAN-60), reached after onboarding creates the store. The backend authorizes the read from
 * the session, so an id that is not the caller's store, or is malformed, is a 404. If the backend cannot be
 * reached the client component starts from an unknown status and offers a retry.
 */
export default async function OnboardingStatusPage({ params }: StatusPageProps) {
  const { storeId } = await params;
  if (!isStoreId(storeId)) notFound();

  const result = await fetchStoreStatus(storeId);
  if (!result.success && result.reason === 'not_found') notFound();

  return (
    <div className="mx-auto max-w-lg">
      <Card>
        <CardHeader>
          <h1 className="text-2xl font-semibold leading-none tracking-tight">Store setup</h1>
          <CardDescription>We will let you know here when your store is ready.</CardDescription>
        </CardHeader>
        <CardContent>
          <ProvisioningStatus
            storeId={storeId}
            storeName={result.success ? result.data.name : 'Your store'}
            initialStatus={result.success ? result.data.status : 'UNKNOWN'}
          />
        </CardContent>
      </Card>
    </div>
  );
}
