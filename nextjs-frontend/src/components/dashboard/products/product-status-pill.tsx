import { Pencil } from 'lucide-react';
import { StatusPill } from '@/components/ui/status-pill';
import type { ProductStatus } from '@/lib/products/schema';

/** Active products are live; drafts are unpublished (the API has no archived status). */
export function ProductStatusPill({ status }: { status: ProductStatus }) {
  return status === 'active' ? (
    <StatusPill variant="good">Active</StatusPill>
  ) : (
    <StatusPill variant="neutral" icon={Pencil}>
      Draft
    </StatusPill>
  );
}
