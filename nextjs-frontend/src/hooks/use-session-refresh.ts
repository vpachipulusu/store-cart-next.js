'use client';

import { useEffect } from 'react';
import { auth } from '@/lib/firebase/client';
import { onIdTokenChanged, signOut } from 'firebase/auth';
import { refreshSessionAction } from '@/app/actions/auth-actions';

/**
 * Refreshes the server session cookie through the API with a fresh ID token. When the API refuses
 * (revoked session, or an ID token too old to mint a cookie) the server has already dropped the session
 * cookie, so the Firebase user is signed out too and sent to /login. Never a silent success.
 */
async function refreshOrSignIn(idToken: string): Promise<void> {
  const result = await refreshSessionAction(idToken);
  if (!result.success && result.data?.signInRequired === true) {
    await signOut(auth).catch(() => undefined);
    window.location.assign('/login');
  }
}

/**
 * Hook to automatically refresh the server session cookie when the
 * Firebase ID token refreshes (~every 55 minutes).
 *
 * This prevents the 5-day session cookie from expiring while the
 * user is actively using the app.
 */
export function useSessionRefresh() {
  useEffect(() => {
    // Listen for token changes (Firebase auto-refreshes ~every hour)
    const unsubscribe = onIdTokenChanged(auth, async (user) => {
      if (user) {
        try {
          const idToken = await user.getIdToken();
          await refreshOrSignIn(idToken);
        } catch (error) {
          console.error('Session refresh failed:', error);
        }
      }
    });

    // Also set up a periodic refresh every 50 minutes
    const interval = setInterval(
      async () => {
        const user = auth.currentUser;
        if (user) {
          try {
            const idToken = await user.getIdToken(true); // Force refresh
            await refreshOrSignIn(idToken);
          } catch (error) {
            console.error('Periodic session refresh failed:', error);
          }
        }
      },
      50 * 60 * 1000 // 50 minutes
    );

    return () => {
      unsubscribe();
      clearInterval(interval);
    };
  }, []);
}
