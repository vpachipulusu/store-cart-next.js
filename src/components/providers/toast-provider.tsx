"use client";

import * as React from "react";
import { Toaster } from "@/components/ui/toaster";

/**
 * Toast Provider Component
 *
 * Provides toast notification functionality across the application
 * Uses shadcn/ui Toaster component for consistent styling
 *
 * @param children - Child components to wrap
 */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  return (
    <>
      {children}
      <Toaster />
    </>
  );
}
