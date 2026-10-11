"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { auth } from "@/lib/firebase/client";
import { onAuthStateChanged } from "firebase/auth";
import { resendVerificationEmail } from "@/lib/firebase/auth-helpers";
import { verifyTokenAction } from "@/app/actions/auth-actions";

export default function VerifyEmailPage() {
  const router = useRouter();
  const [isResending, setIsResending] = useState(false);
  const [resendSuccess, setResendSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [userEmail, setUserEmail] = useState<string>("");

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, (user) => {
      if (!user) {
        // User not logged in, redirect to login
        router.push("/login");
        return;
      }

      setUserEmail(user.email || "");

      // Check if email is already verified
      if (user.emailVerified) {
        router.push("/dashboard");
      }
    });

    return () => unsubscribe();
  }, [router]);

  const handleResendEmail = async () => {
    try {
      setIsResending(true);
      setError(null);
      setResendSuccess(false);

      const user = auth.currentUser;
      if (!user) {
        setError("No user found. Please log in again.");
        return;
      }

      const { error: resendError } = await resendVerificationEmail(user);

      if (resendError) {
        setError(resendError);
        return;
      }

      setResendSuccess(true);
    } catch (error) {
      setError("Failed to resend verification email. Please try again.");
      console.error("Resend email error:", error);
    } finally {
      setIsResending(false);
    }
  };

  const handleRefresh = async () => {
    const user = auth.currentUser;
    if (user) {
      await user.reload();
      if (user.emailVerified) {
        // Get fresh token and update session cookies (including email-verified)
        const idToken = await user.getIdToken(true);
        await verifyTokenAction(idToken);
        router.push("/dashboard");
      } else {
        setError("Email not verified yet. Please check your inbox.");
      }
    }
  };

  return (
    <Card>
      <CardHeader className="space-y-1">
        <div className="flex justify-center mb-4">
          <div className="rounded-full bg-theme-accent/10 p-3">
            <svg
              className="h-6 w-6 text-theme-accent"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
              />
            </svg>
          </div>
        </div>
        <CardTitle className="text-2xl text-center">
          Verify your email
        </CardTitle>
        <CardDescription className="text-center">
          We've sent a verification link to{" "}
          <span className="font-medium text-foreground">{userEmail}</span>
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {error && (
          <div className="rounded-md bg-destructive/15 p-3 text-sm text-destructive">
            {error}
          </div>
        )}

        {resendSuccess && (
          <div className="rounded-md bg-green-50 p-3 text-sm text-green-800 dark:bg-green-900/20 dark:text-green-400">
            Verification email sent! Please check your inbox.
          </div>
        )}

        <div className="text-center text-sm text-muted-foreground space-y-2">
          <p>Click the link in the email to verify your account.</p>
          <p>
            If you don't see the email, check your spam folder or request a new
            one.
          </p>
        </div>

        <div className="space-y-2">
          <Button
            onClick={handleResendEmail}
            variant="outline"
            className="w-full"
            disabled={isResending}
          >
            {isResending ? (
              <>
                <div className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                Sending...
              </>
            ) : (
              "Resend verification email"
            )}
          </Button>

          <Button onClick={handleRefresh} className="w-full">
            I've verified my email
          </Button>
        </div>
      </CardContent>
      <CardFooter>
        <p className="text-center text-sm text-muted-foreground w-full">
          Wrong email?{" "}
          <Link
            href="/signup"
            className="font-medium text-primary hover:underline"
          >
            Create a new account
          </Link>
        </p>
      </CardFooter>
    </Card>
  );
}
