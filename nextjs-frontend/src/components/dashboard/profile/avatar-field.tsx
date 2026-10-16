'use client';

import { useRef } from 'react';
import type { ChangeEvent } from 'react';
import { Upload, User as UserIcon } from 'lucide-react';

import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';

interface AvatarFieldProps {
  avatarUrl: string;
  name: string;
  initial: string;
  onSelect: (file: File) => void;
}

/** Avatar preview and a real button that opens the hidden file input, so keyboard users can reach it. */
export function AvatarField({ avatarUrl, name, initial, onSelect }: AvatarFieldProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  function handleChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) onSelect(file);
    event.target.value = '';
  }

  return (
    <div className="flex flex-col items-start gap-4 sm:flex-row sm:items-center sm:gap-6">
      <Avatar className="h-24 w-24 shrink-0">
        <AvatarImage src={avatarUrl} alt={name} />
        <AvatarFallback className="text-2xl">
          {initial || <UserIcon aria-hidden="true" />}
        </AvatarFallback>
      </Avatar>

      <div className="space-y-2">
        <Button type="button" variant="outline" onClick={() => inputRef.current?.click()}>
          <Upload aria-hidden="true" />
          Upload Photo
        </Button>
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          aria-label="Choose a profile photo"
          className="hidden"
          onChange={handleChange}
        />
        <p className="text-xs text-muted-foreground">JPG, PNG or GIF. Max size 2MB.</p>
      </div>
    </div>
  );
}
