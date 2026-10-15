'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { onAuthStateChanged } from 'firebase/auth';
import { auth } from '@/lib/firebase/client';
import { reauthenticate, reauthMethodFor, type ReauthMethod } from '@/lib/firebase/reauth';

const PROVIDER_LABEL: Record<Exclude<ReauthMethod, 'password'>, string> = {
  google: 'Google',
  github: 'GitHub',
};

type ReauthDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel: string;
  destructive?: boolean;
  /** Extra inputs rendered above the password field (a typed confirmation, an authenticator code). */
  children?: ReactNode;
  /** Disables the confirm button until the extra inputs are valid. */
  canConfirm?: boolean;
  /**
   * Runs with the fresh Firebase ID token once the user has re-authenticated. Resolves to an error message
   * to show in the dialog, or null on success. The token must not be stored or logged by the caller.
   */
  onConfirm: (idToken: string) => Promise<string | null>;
};

/**
 * Re-authentication step for sensitive account actions (KAN-180): password re-entry for email/password
 * users, the provider popup for OAuth users. The password lives only in this component's state and is
 * cleared when the dialog closes.
 */
export function ReauthDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  destructive = false,
  children,
  canConfirm = true,
  onConfirm,
}: ReauthDialogProps) {
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isWorking, setIsWorking] = useState(false);
  const [method, setMethod] = useState<ReauthMethod | null>(() =>
    reauthMethodFor(auth.currentUser)
  );

  // Firebase restores the signed-in user asynchronously after a page load, so follow it rather than read it once.
  useEffect(() => onAuthStateChanged(auth, (user) => setMethod(reauthMethodFor(user))), []);

  function handleOpenChange(next: boolean) {
    if (isWorking) return;
    if (!next) {
      setPassword('');
      setError(null);
    }
    onOpenChange(next);
  }

  async function handleConfirm() {
    if (!method) {
      setError('This account cannot be re-authenticated here. Sign in again and retry.');
      return;
    }
    setIsWorking(true);
    setError(null);
    try {
      const fresh = await reauthenticate(method, password);
      if (fresh.error !== null) {
        setError(fresh.error);
        return;
      }
      const failure = await onConfirm(fresh.idToken);
      if (failure) setError(failure);
    } catch {
      setError('An unexpected error occurred');
    } finally {
      setPassword('');
      setIsWorking(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          {children}
          {method === 'password' || method === null ? (
            <div>
              <Label htmlFor="reauth-password">Confirm your password</Label>
              <Input
                id="reauth-password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              You will be asked to sign in with {PROVIDER_LABEL[method]} again to confirm it is you.
            </p>
          )}
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)} disabled={isWorking}>
            Cancel
          </Button>
          <Button
            variant={destructive ? 'destructive' : 'default'}
            onClick={handleConfirm}
            disabled={
              isWorking ||
              !canConfirm ||
              (method !== 'google' && method !== 'github' && password.length === 0)
            }
          >
            {isWorking && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
