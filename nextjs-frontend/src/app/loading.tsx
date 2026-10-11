export default function Loading() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="flex flex-col items-center gap-6">
        <div className="relative h-12 w-12">
          <div className="absolute inset-0 rounded-full border-2 border-theme-accent/20" />
          <div className="absolute inset-0 animate-spin rounded-full border-2 border-transparent border-t-theme-accent" />
        </div>
        <p className="text-sm uppercase tracking-widest text-muted-foreground">
          Loading
        </p>
      </div>
    </div>
  );
}
