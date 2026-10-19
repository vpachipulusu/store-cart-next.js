'use client';

import { useRef, useState, useTransition } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { useToast } from '@/hooks/use-toast';
import type { StoreStatus } from '@/lib/api/admin-stores';
import { STUCK_AFTER_MINUTES } from '@/lib/stores/provisioning';
import {
  migrateStoreAction,
  reprovisionStoreAction,
  suspendStoreAction,
  unsuspendStoreAction,
} from '@/app/actions/admin-store-actions';

type StoreRowActionsProps = {
  storeId: string;
  storeName: string;
  status: StoreStatus;
  /** PROVISIONING with no change past the backend threshold (KAN-255): the re-run fails it and starts a new run. */
  stalled?: boolean;
};

type ActionResult = { success: boolean; data?: unknown; error?: string };

const GENERIC_ERROR = 'Something went wrong. Please try again.';

/**
 * Suspend, unsuspend, re-run migrations and re-run provisioning for one store (KAN-63). Suspending asks first
 * because the storefront goes offline; re-running provisioning asks first because it starts a new run that counts
 * against the attempt cap (only FAILED stores, and PROVISIONING stores stuck past the threshold, are offered it). Migrations and unsuspend are safe to repeat.
 */
export function StoreRowActions({
  storeId,
  storeName,
  status,
  stalled = false,
}: StoreRowActionsProps) {
  const router = useRouter();
  const { toast } = useToast();
  const [pending, startTransition] = useTransition();
  const [confirmSuspend, setConfirmSuspend] = useState(false);
  const [confirmReprovision, setConfirmReprovision] = useState(false);
  // Set synchronously, so two clicks in the same tick cannot both start a request before `pending` renders.
  const inFlight = useRef(false);
  const container = useRef<HTMLDivElement>(null);

  const canSuspend = status === 'ACTIVE';
  const canUnsuspend = status === 'SUSPENDED';
  const canMigrate = status === 'ACTIVE' || status === 'SUSPENDED';
  const isStuck = status === 'PROVISIONING' && stalled;
  const canReprovision = status === 'FAILED' || isStuck;

  if (!canSuspend && !canUnsuspend && !canMigrate && !canReprovision) {
    return <span className="text-sm text-muted-foreground">No actions</span>;
  }

  // Refreshing inside the transition keeps the buttons disabled until the new row has arrived.
  function refreshRow() {
    startTransition(() => router.refresh());
  }

  // The button that opened a dialog is disabled while the request runs and may be gone afterwards (the store
  // changes status), which would drop focus to the page. The table row outlives the change, so focus moves there.
  function focusRow() {
    const target = container.current?.closest<HTMLElement>('tr') ?? container.current;
    if (!target) return;
    if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
    target.focus();
  }

  function run(action: (id: string) => Promise<ActionResult>) {
    if (inFlight.current) return;
    inFlight.current = true;
    startTransition(async () => {
      try {
        const result = await action(storeId);
        if (result.success) {
          const message = (result.data as { message?: string } | undefined)?.message;
          toast({ title: 'Success', description: message });
          refreshRow();
        } else {
          toast({
            title: 'Error',
            description: result.error ?? GENERIC_ERROR,
            variant: 'destructive',
          });
          // The row may be stale (another admin changed the store): show what the store is now.
          refreshRow();
        }
      } catch {
        toast({ title: 'Error', description: GENERIC_ERROR, variant: 'destructive' });
        refreshRow();
      } finally {
        inFlight.current = false;
        focusRow();
      }
    });
  }

  return (
    <div ref={container} className="flex flex-wrap justify-end gap-2 outline-none">
      {canMigrate && (
        <Button
          variant="outline"
          size="sm"
          disabled={pending}
          aria-label={`Run migrations for ${storeName}`}
          onClick={() => run(migrateStoreAction)}
        >
          Run migrations
        </Button>
      )}
      {canReprovision && (
        <Button
          variant="outline"
          size="sm"
          disabled={pending}
          aria-label={`Re-run provisioning for ${storeName}`}
          onClick={() => setConfirmReprovision(true)}
        >
          Re-run provisioning
        </Button>
      )}
      {canUnsuspend && (
        <Button
          variant="outline"
          size="sm"
          disabled={pending}
          aria-label={`Unsuspend ${storeName}`}
          onClick={() => run(unsuspendStoreAction)}
        >
          Unsuspend
        </Button>
      )}
      {canSuspend && (
        <Button
          variant="destructive"
          size="sm"
          disabled={pending}
          aria-label={`Suspend ${storeName}`}
          onClick={() => setConfirmSuspend(true)}
        >
          Suspend
        </Button>
      )}

      <Dialog open={confirmSuspend} onOpenChange={setConfirmSuspend}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Suspend {storeName}?</DialogTitle>
            <DialogDescription>
              The storefront goes offline and the merchant cannot change the store until you
              unsuspend it.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmSuspend(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={pending}
              onClick={() => {
                setConfirmSuspend(false);
                run(suspendStoreAction);
              }}
            >
              Suspend store
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={confirmReprovision} onOpenChange={setConfirmReprovision}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Re-run provisioning for {storeName}?</DialogTitle>
            <DialogDescription>
              {isStuck
                ? `This store has been provisioning for over ${STUCK_AFTER_MINUTES} minutes without progress. Re-running marks the stuck run failed and starts a new one.`
                : 'This starts a new provisioning run for the failed store.'}{' '}
              Each store can be re-run a limited number of times.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmReprovision(false)}>
              Cancel
            </Button>
            <Button
              disabled={pending}
              onClick={() => {
                setConfirmReprovision(false);
                run(reprovisionStoreAction);
              }}
            >
              Re-run provisioning
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
