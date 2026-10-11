import { ReactNode } from "react";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden p-4">
      <div className="absolute inset-0 bg-gradient-to-br from-background via-background to-theme-accent/[0.05]" />
      <div className="absolute right-0 top-0 h-1/2 w-1/2 bg-gradient-radial from-theme-accent/[0.06] to-transparent" />
      <div className="absolute bottom-0 left-0 h-1/3 w-1/3 bg-gradient-radial from-accent/[0.04] to-transparent" />
      <div className="relative w-full max-w-md animate-scale-in">
        {children}
      </div>
    </div>
  );
}
