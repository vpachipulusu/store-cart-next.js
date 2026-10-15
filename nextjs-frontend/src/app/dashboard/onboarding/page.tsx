import { redirect } from 'next/navigation';
import { fetchOnboardingState } from '@/lib/api/onboarding';
import { OnboardingForm } from '@/components/onboarding/onboarding-form';
import { Card, CardContent, CardDescription, CardHeader } from '@/components/ui/card';

export const metadata = {
  title: 'Set up your store',
  description: 'Create your business and first store',
};

/**
 * Merchant onboarding (KAN-60). Lives under /dashboard, so the proxy's session check and the dashboard layout's
 * verified-session check already apply. A user who already has a store is sent to the dashboard; one whose
 * business exists without a store sees the form for the store only.
 */
export default async function OnboardingPage() {
  const state = await fetchOnboardingState();
  if (state.success && state.data.kind === 'done') redirect('/dashboard');

  return (
    <div className="mx-auto max-w-lg">
      <Card>
        <CardHeader>
          <h1 className="text-2xl font-semibold leading-none tracking-tight">Set up your store</h1>
          <CardDescription>Tell us about your business and name your first store.</CardDescription>
        </CardHeader>
        <CardContent>
          {state.success ? (
            <OnboardingForm
              resumeOrganizationName={
                state.data.kind === 'resume' ? state.data.organizationName : undefined
              }
            />
          ) : (
            <p role="alert" className="text-sm text-destructive">
              We could not load your account. Reload the page to try again.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
