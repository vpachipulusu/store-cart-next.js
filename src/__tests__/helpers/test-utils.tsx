import { render, RenderOptions } from '@testing-library/react';
import { ReactElement } from 'react';

// Add any providers your app needs here
function AllTheProviders({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

// Custom render function that includes providers
export function renderWithProviders(
  ui: ReactElement,
  options?: Omit<RenderOptions, 'wrapper'>
) {
  return render(ui, { wrapper: AllTheProviders, ...options });
}

// Re-export everything from React Testing Library
export * from '@testing-library/react';
export { renderWithProviders as render };
