'use client';

import Link from 'next/link';
import { MoreHorizontal, Eye, Edit, Ban } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

type UserRowActionsProps = {
  userId: string;
  /** Name or email, so the trigger is distinguishable per row for screen readers. */
  userLabel?: string;
};

export function UserRowActions({ userId, userLabel }: UserRowActionsProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="size-11 p-0 hover:bg-accent">
          <span className="sr-only">{userLabel ? `Open menu for ${userLabel}` : 'Open menu'}</span>
          <MoreHorizontal className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>Actions</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href={`/admin/users/${userId}`} className="flex items-center">
            <Eye className="mr-2 h-4 w-4" />
            View Details
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem>
          <Edit className="mr-2 h-4 w-4" />
          Edit User
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem className="text-destructive focus:text-destructive">
          <Ban className="mr-2 h-4 w-4" />
          Suspend User
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
