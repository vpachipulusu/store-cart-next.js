'use client';

import { useTransition } from 'react';
import { useRouter } from 'next/navigation';
import { Store } from 'lucide-react';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { selectStoreAction } from '@/app/actions/store-actions';
import { useToast } from '@/hooks/use-toast';
import type { MerchantStore } from '@/lib/stores/selection';

interface StoreSwitcherProps {
  stores: ReadonlyArray<MerchantStore>;
  selectedStoreId: string;
}

/** Shows the selected store; with several stores it is a keyboard-accessible switcher (44px trigger). */
export function StoreSwitcher({ stores, selectedStoreId }: StoreSwitcherProps) {
  const router = useRouter();
  const { toast } = useToast();
  const [isPending, startTransition] = useTransition();

  const selected = stores.find((store) => store.id === selectedStoreId) ?? stores[0];
  if (!selected) return null;

  if (stores.length === 1) {
    return (
      <div
        className="flex h-11 items-center gap-2 text-sm font-medium"
        data-testid="store-name"
        role="group"
        aria-label="Current store"
      >
        <Store className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        <span className="max-w-[12rem] truncate">{selected.name}</span>
      </div>
    );
  }

  const handleChange = (storeId: string) => {
    if (storeId === selected.id) return;
    startTransition(async () => {
      const result = await selectStoreAction(storeId);
      if (!result.success) {
        toast({
          title: 'Could not switch store',
          description: result.error,
          variant: 'destructive',
        });
        return;
      }
      router.refresh();
    });
  };

  return (
    <Select value={selected.id} onValueChange={handleChange} disabled={isPending}>
      <SelectTrigger
        aria-label="Switch store"
        data-testid="store-switcher"
        className="w-44 max-w-[45vw] sm:w-52"
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {stores.map((store) => (
          <SelectItem
            key={store.id}
            value={store.id}
            className="min-h-11"
            aria-label={`${store.name}, ${store.organizationName}`}
          >
            {store.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
