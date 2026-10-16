'use client';

import { useTransition } from 'react';
import { useRouter } from 'next/navigation';
import { ChevronsUpDown, Loader2, Store } from 'lucide-react';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { selectStoreAction } from '@/app/actions/store-actions';
import { useToast } from '@/hooks/use-toast';
import { cn } from '@/lib/utils';
import type { MerchantStore } from '@/lib/stores/selection';

type StoreSwitcherVariant = 'header' | 'sidebar';

interface StoreSwitcherProps {
  stores: ReadonlyArray<MerchantStore>;
  selectedStoreId: string;
  /** `sidebar` sits on the inverse (--feature) panel; `header` is the compact form used below 900px. */
  variant?: StoreSwitcherVariant;
}

const SWITCH_FAILED_TITLE = 'Could not switch store';
const SWITCH_FAILED_FALLBACK = 'Please try again.';

/** The 52px slot (design plan 5.2). Colours are tokens only; the sidebar form stays light on --feature in both modes. */
const SLOT_CLASS = 'flex h-[52px] items-center gap-3 rounded-md px-3 text-start';
const VARIANT_CLASS: Record<StoreSwitcherVariant, string> = {
  sidebar: 'w-full text-background dark:text-foreground',
  header: 'w-52 max-w-[45vw] text-foreground',
};
const HOVER_CLASS: Record<StoreSwitcherVariant, string> = {
  sidebar: 'hover:bg-background/10 dark:hover:bg-foreground/10',
  header: 'hover:bg-secondary',
};
const MUTED_CLASS: Record<StoreSwitcherVariant, string> = {
  sidebar: 'text-background/70 dark:text-foreground/70',
  header: 'text-muted-foreground',
};

function StoreText({ store, variant }: { store: MerchantStore; variant: StoreSwitcherVariant }) {
  return (
    <>
      <Store
        className={cn('h-[18px] w-[18px] shrink-0', MUTED_CLASS[variant])}
        aria-hidden="true"
      />
      <span className="flex min-w-0 flex-1 flex-col leading-tight">
        <span className="truncate text-sm font-semibold">{store.name}</span>
        <span className={cn('truncate text-xs', MUTED_CLASS[variant])}>
          {store.organizationName}
        </span>
      </span>
    </>
  );
}

/**
 * Shows the selected store and organisation. One store is a plain label; several make a "Switch store" menu.
 * The selection is only a preference: `selectStoreAction` validates the id against the user's own stores, and
 * the server re-validates it on every request, so nothing here is an authorization boundary.
 */
export function StoreSwitcher({ stores, selectedStoreId, variant = 'header' }: StoreSwitcherProps) {
  const router = useRouter();
  const { toast } = useToast();
  const [isPending, startTransition] = useTransition();

  const selected = stores.find((store) => store.id === selectedStoreId) ?? stores[0];
  if (!selected) return null;

  if (stores.length === 1) {
    return (
      <div
        className={cn(SLOT_CLASS, VARIANT_CLASS[variant])}
        data-testid="store-name"
        role="group"
        aria-label="Current store"
      >
        <StoreText store={selected} variant={variant} />
      </div>
    );
  }

  const reportFailure = (description?: string) =>
    toast({
      title: SWITCH_FAILED_TITLE,
      description: description ?? SWITCH_FAILED_FALLBACK,
      variant: 'destructive',
    });

  const handleChange = (storeId: string) => {
    if (storeId === selected.id || isPending) return;
    startTransition(async () => {
      try {
        const result = await selectStoreAction(storeId);
        if (!result.success) {
          reportFailure(result.error);
          return;
        }
        router.refresh();
      } catch {
        reportFailure();
      }
    });
  };

  return (
    <>
      <span role="status" aria-live="polite" className="sr-only">
        {isPending ? 'Switching store…' : ''}
      </span>
      <DropdownMenu>
        <DropdownMenuTrigger
          aria-label={`Switch store, current ${selected.name}, ${selected.organizationName}`}
          data-testid="store-switcher"
          aria-busy={isPending}
          className={cn(
            SLOT_CLASS,
            VARIANT_CLASS[variant],
            HOVER_CLASS[variant],
            'transition-colors',
            isPending && 'opacity-70'
          )}
        >
          <StoreText store={selected} variant={variant} />
          {isPending ? (
            <Loader2
              className={cn('h-4 w-4 shrink-0 animate-spin', MUTED_CLASS[variant])}
              aria-hidden="true"
            />
          ) : (
            <ChevronsUpDown
              className={cn('h-4 w-4 shrink-0', MUTED_CLASS[variant])}
              aria-hidden="true"
            />
          )}
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="start"
          className="min-w-[var(--radix-dropdown-menu-trigger-width)]"
        >
          <DropdownMenuRadioGroup value={selected.id} onValueChange={handleChange}>
            {stores.map((store) => (
              <DropdownMenuRadioItem
                key={store.id}
                value={store.id}
                disabled={isPending}
                className="min-h-11 flex-col items-start justify-center [&>span:first-child]:top-1/2 [&>span:first-child]:-translate-y-1/2"
              >
                <span className="text-sm font-medium">{store.name}</span>
                <span className="text-xs text-muted-foreground">{store.organizationName}</span>
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </>
  );
}
