import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';

const loaderCalls: Array<{ name: string; options: Record<string, unknown> }> = [];

vi.mock('next/font/google', () => {
  const loader = (name: string) => (options: Record<string, unknown>) => {
    loaderCalls.push({ name, options });
    return {
      className: `cls-${name}`,
      variable: `var${String(options.variable)}`,
      style: { fontFamily: name },
    };
  };
  return {
    Inter: loader('Inter'),
    Open_Sans: loader('Open_Sans'),
    Roboto: loader('Roboto'),
    Lato: loader('Lato'),
    Poppins: loader('Poppins'),
    Nunito: loader('Nunito'),
    Work_Sans: loader('Work_Sans'),
    Source_Sans_3: loader('Source_Sans_3'),
    Montserrat: loader('Montserrat'),
    Raleway: loader('Raleway'),
    Fraunces: loader('Fraunces'),
  };
});

const mockActiveFont = vi.fn();

vi.mock('@/app/actions/theme-actions', () => ({
  getActiveTheme: vi.fn().mockResolvedValue('luxury'),
}));
vi.mock('@/app/actions/font-actions', () => ({
  getActiveFont: () => mockActiveFont(),
}));
vi.mock('@/config/themes', () => ({ generateThemeCSS: () => ':root{}' }));
vi.mock('@/components/providers/theme-provider', () => ({ ThemeProvider: () => null }));
vi.mock('@/components/providers/query-provider', () => ({ QueryProvider: () => null }));
vi.mock('@/components/providers/toast-provider', () => ({ ToastProvider: () => null }));
vi.mock('@/app/globals.css', () => ({}));

function classOf(element: ReactElement): string {
  return (element.props as { className?: string }).className ?? '';
}

describe('display font (KAN-175)', () => {
  beforeEach(() => {
    vi.resetModules();
    loaderCalls.length = 0;
    mockActiveFont.mockReset();
  });

  it('loads Fraunces as --font-display with opsz axis, latin subset, swap and no weight', async () => {
    await import('@/config/fonts');

    const fraunces = loaderCalls.find((call) => call.name === 'Fraunces');
    expect(fraunces).toBeDefined();
    expect(fraunces?.options).toMatchObject({
      axes: ['opsz'],
      subsets: ['latin'],
      display: 'swap',
      variable: '--font-display',
    });
    expect(fraunces?.options).not.toHaveProperty('weight');
    expect(fraunces?.options).not.toHaveProperty('style');
    expect(fraunces?.options.fallback).toEqual(['Georgia', 'Times New Roman', 'serif']);
  });

  it('never reuses the body font variable for the display font', async () => {
    const { AVAILABLE_FONTS, displayFont } = await import('@/config/fonts');

    for (const entry of Object.values(AVAILABLE_FONTS)) {
      expect(entry.font.variable).not.toBe(displayFont.variable);
    }
  });

  it.each(['inter', 'poppins', 'raleway'])(
    'puts the display variable on <html> and only the %s body variable on <body>',
    async (fontId) => {
      mockActiveFont.mockResolvedValue(fontId);
      const { default: RootLayout } = await import('@/app/layout');
      const { displayFont, getFontById } = await import('@/config/fonts');

      const html = (await RootLayout({ children: null })) as ReactElement;
      const body = (html.props as { children: ReactElement[] }).children[1];
      const bodyFont = getFontById(fontId).font;

      expect(classOf(html)).toContain(displayFont.variable);
      expect(classOf(html)).not.toContain(bodyFont.variable);
      expect(classOf(body)).toContain(bodyFont.variable);
      expect(classOf(body)).not.toContain(displayFont.variable);
    }
  );

  it('keeps the display class identical across different admin body fonts', async () => {
    mockActiveFont.mockResolvedValueOnce('inter').mockResolvedValueOnce('lato');
    const { default: RootLayout } = await import('@/app/layout');

    const first = (await RootLayout({ children: null })) as ReactElement;
    const second = (await RootLayout({ children: null })) as ReactElement;

    expect(classOf(first)).toBe(classOf(second));
  });
});
