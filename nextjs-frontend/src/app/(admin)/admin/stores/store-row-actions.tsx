'use client';

import { useState, useTransition } from 'react';
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
import {
  migrateStoreAction,
  suspendStoreAction,
  unsuspendStoreAction,
} from '@/app/actions/admin-store-actions';

type StoreRowActionsProps = {
  storeId: string;
  storeName: string;
  status: StoreStatus;
};

type ActionResult = { success: boolean; data?: unknown; error?: string };

const GENERIC_ERROR = 'Something went wrong. Please try again.';

/**
 * Suspend, unsuspend and re-run migrations for one store (KAN-63). Suspending asks first because the storefront
 * goes offline; the other two are safe to repeat. Re-running provisioning is KAN-200 and is not offered.
 */
export function StoreRowActions({ storeId, storeName, status }: StoreRowActionsProps) {
  const router = useRouter();
  const { toast } = useToast();
  const [pending, startTransition] = useTransition();
  const [confirmSuspend, setConfirmSuspend] = useState(false);

  const canSuspend = status === 'ACTIVE';
  const canUnsuspend = status === 'SUSPENDED';
  const canMigrate = status === 'ACTIVE' || status === 'SUSPENDED';

  if (!canSuspend && !canUnsuspend && !canMigrate) {
    return <span className="text-sm text-muted-foreground">No actions</span>;
  }

  function run(action: (id: string) => Promise<ActionResult>) {
    startTransition(async () => {
      try {
        const result = await action(storeId);
        if (result.success) {
          const message = (result.data as { message?: string } | undefined)?.message;
          toast({ title: 'Success', description: message });
          router.refresh();
        } else {
          toast({
            title: 'Error',
            description: result.error ?? GENERIC_ERROR,
            variant: 'destructive',
          });
          // The row may be stale (another admin changed the store): show what the store is now.
          router.refresh();
        }
      } catch {
        toast({ title: 'Error', description: GENERIC_ERROR, variant: 'destructive' });
      }
    });
  }

  return (
    <div className="flex flex-wrap justify-end gap-2">
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
    </div>
  );
}
