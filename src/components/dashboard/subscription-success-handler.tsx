'use client';

import { useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { CheckCircle2, Loader2, XCircle } from 'lucide-react';
import {
  getSubscriptionStatusAction,
  verifyUpgradeSessionAction,
} from '@/app/actions/subscription-actions';

export function SubscriptionSuccessHandler() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const upgradeSuccess = searchParams.get('upgrade') === 'success';

  const [isPolling, setIsPolling] = useState(false);
  const [pollCount, setPollCount] = useState(0);
  const [subscriptionUpdated, setSubscriptionUpdated] = useState(false);
  const [isVerifying, setIsVerifying] = useState(upgradeSuccess);
  const [isValidSession, setIsValidSession] = useState(false);

  // Verify checkout session first
  useEffect(() => {
    if (!upgradeSuccess) return;

    const verifySession = async () => {
      setIsVerifying(true);
      try {
        const result = await verifyUpgradeSessionAction();

        if (result.success && result.data?.valid) {
          // Valid checkout session - proceed with polling
          setIsValidSession(true);
          setIsPolling(true);
        } else {
          // Invalid or fake session - remove query param immediately
          console.warn('Invalid checkout session:', result.data?.reason);
          router.replace('/dashboard');
        }
      } catch (error) {
        console.error('Error verifying checkout session:', error);
        router.replace('/dashboard');
      } finally {
        setIsVerifying(false);
      }
    };

    verifySession();
  }, [upgradeSuccess, router]);

  // Poll for subscription status only if session is valid
  useEffect(() => {
    if (!isValidSession || subscriptionUpdated) return;

    let pollInterval: NodeJS.Timeout;
    const maxPolls = 10; // Poll for up to 30 seconds (10 * 3 seconds)

    const checkSubscription = async () => {
      try {
        const result = await getSubscriptionStatusAction();

        if (result.success && result.data) {
          const { subscriptionTier, subscriptionStatus } = result.data;

          // Check if subscription has been updated to pro or enterprise
          if (subscriptionTier !== 'free' && subscriptionStatus === 'active') {
            setSubscriptionUpdated(true);
            setIsPolling(false);

            // Wait a moment for the success message, then refresh the page
            setTimeout(() => {
              // Remove the query parameter and refresh
              router.replace('/dashboard');
              router.refresh();
            }, 2000);

            return true;
          }
        }

        return false;
      } catch (error) {
        console.error('Error checking subscription:', error);
        return false;
      }
    };

    // Initial check immediately
    checkSubscription().then((updated) => {
      if (updated) return;

      // Start polling if not updated yet
      pollInterval = setInterval(async () => {
        setPollCount((prev) => {
          const newCount = prev + 1;

          // Stop polling after max attempts
          if (newCount >= maxPolls) {
            setIsPolling(false);
            clearInterval(pollInterval);
            // Refresh anyway after timeout
            setTimeout(() => {
              router.replace('/dashboard');
              router.refresh();
            }, 1000);
            return newCount;
          }

          return newCount;
        });

        const updated = await checkSubscription();
        if (updated && pollInterval) {
          clearInterval(pollInterval);
        }
      }, 3000); // Poll every 3 seconds
    });

    return () => {
      if (pollInterval) {
        clearInterval(pollInterval);
      }
    };
  }, [isValidSession, subscriptionUpdated, router]);

  // Don't show anything if not upgrade success or still verifying
  if (!upgradeSuccess || (isVerifying && !isValidSession)) return null;

  return (
    <Alert className="border-green-500 bg-green-50 dark:bg-green-950">
      <div className="flex items-start gap-3">
        {subscriptionUpdated ? (
          <CheckCircle2 className="h-5 w-5 text-green-600 dark:text-green-400" />
        ) : (
          <Loader2 className="h-5 w-5 animate-spin text-green-600 dark:text-green-400" />
        )}
        <div className="flex-1">
          <AlertTitle className="text-green-900 dark:text-green-100">
            {subscriptionUpdated ? 'Subscription Activated!' : 'Processing Your Subscription...'}
          </AlertTitle>
          <AlertDescription className="text-green-800 dark:text-green-200">
            {subscriptionUpdated
              ? 'Your subscription has been successfully activated. Refreshing your dashboard...'
              : isPolling
                ? 'Please wait while we confirm your payment and activate your subscription. This usually takes just a few seconds.'
                : "Your payment was successful. Please refresh the page if your subscription status doesn't update automatically."}
          </AlertDescription>
        </div>
      </div>
    </Alert>
  );
}
