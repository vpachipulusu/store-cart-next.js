/**
 * Theme preset definitions for the admin-configurable theme system.
 *
 * Each preset defines complete light + dark mode CSS variable values.
 * The CSS variables control all colors across the app because both
 * standard Tailwind classes (bg-card, text-primary) and theme-accent
 * utility classes resolve through these variables.
 */

export interface ThemeModeVariables {
  // Standard shadcn/ui tokens
  '--background': string;
  '--foreground': string;
  '--card': string;
  '--card-foreground': string;
  '--popover': string;
  '--popover-foreground': string;
  '--primary': string;
  '--primary-foreground': string;
  '--secondary': string;
  '--secondary-foreground': string;
  '--muted': string;
  '--muted-foreground': string;
  '--accent': string;
  '--accent-foreground': string;
  '--destructive': string;
  '--destructive-foreground': string;
  '--border': string;
  '--input': string;
  '--ring': string;
  // CTA (matched surface/text pair per preset; never pair a CTA with a hard-coded text colour)
  '--cta': string;
  '--cta-foreground': string;
  '--cta-hover': string;
  // Accent used as text (links, eyebrows, large numerals)
  '--accent-ink': string;
  // Inverse panel (sidebar, featured plan, CTA band)
  '--feature': string;
  // Semantic status pairs: foreground text on its own tint
  '--good-fg': string;
  '--good-bg': string;
  '--warn-fg': string;
  '--warn-bg': string;
  '--crit-fg': string;
  '--crit-bg': string;
  '--info-fg': string;
  '--info-bg': string;
  // Chart colors
  '--chart-1': string;
  '--chart-2': string;
  '--chart-3': string;
  '--chart-4': string;
  '--chart-5': string;
  // Custom semantic tokens (remapped per theme)
  '--theme-accent': string;
  '--theme-accent-light': string;
  '--theme-accent-dark': string;
  '--theme-surface': string;
  '--theme-surface-light': string;
}

export interface ThemePreset {
  name: string;
  label: string;
  description: string;
  previewColors: {
    primary: string;
    accent: string;
    background: string;
  };
  light: ThemeModeVariables;
  dark: ThemeModeVariables;
}

export const DEFAULT_THEME = 'luxury';

export const THEME_PRESETS: Record<string, ThemePreset> = {
  plain: {
    name: 'plain',
    label: 'Plain',
    description: 'Clean, modern SaaS design with professional blue and gray tones',
    previewColors: {
      primary: '#0f172a',
      accent: '#3b82f6',
      background: '#ffffff',
    },
    light: {
      '--background': '0 0% 100%',
      '--foreground': '222.2 84% 4.9%',
      '--card': '0 0% 100%',
      '--card-foreground': '222.2 84% 4.9%',
      '--popover': '0 0% 100%',
      '--popover-foreground': '222.2 84% 4.9%',
      '--primary': '222.2 47.4% 11.2%',
      '--primary-foreground': '210 40% 98%',
      '--secondary': '210 40% 96.1%',
      '--secondary-foreground': '222.2 47.4% 11.2%',
      '--muted': '210 40% 96.1%',
      '--muted-foreground': '215 16% 38%',
      '--accent': '210 40% 96.1%',
      '--accent-foreground': '222.2 47.4% 11.2%',
      '--destructive': '0 72% 42%',
      '--destructive-foreground': '210 40% 98%',
      '--border': '214.3 31.8% 91.4%',
      '--input': '215 14% 54%',
      '--ring': '222.2 84% 4.9%',
      '--cta': '221 83% 53%',
      '--cta-foreground': '0 0% 100%',
      '--cta-hover': '221 83% 45%',
      '--accent-ink': '221 83% 40%',
      '--feature': '222 47% 11%',
      '--good-fg': '152 60% 22%',
      '--good-bg': '152 40% 91%',
      '--warn-fg': '30 90% 24%',
      '--warn-bg': '42 90% 89%',
      '--crit-fg': '0 70% 36%',
      '--crit-bg': '0 80% 96%',
      '--info-fg': '217 70% 34%',
      '--info-bg': '217 80% 95%',
      '--chart-1': '221 83% 53%',
      '--chart-2': '160 60% 45%',
      '--chart-3': '30 80% 55%',
      '--chart-4': '280 65% 60%',
      '--chart-5': '340 75% 55%',
      '--theme-accent': '217 91% 60%',
      '--theme-accent-light': '213 94% 72%',
      '--theme-accent-dark': '221 83% 53%',
      '--theme-surface': '222.2 84% 4.9%',
      '--theme-surface-light': '215 25% 27%',
    },
    dark: {
      '--background': '222.2 84% 4.9%',
      '--foreground': '210 40% 98%',
      '--card': '222.2 84% 7%',
      '--card-foreground': '210 40% 98%',
      '--popover': '222.2 84% 7%',
      '--popover-foreground': '210 40% 98%',
      '--primary': '210 40% 98%',
      '--primary-foreground': '222.2 47.4% 11.2%',
      '--secondary': '217.2 32.6% 17.5%',
      '--secondary-foreground': '210 40% 98%',
      '--muted': '217.2 32.6% 17.5%',
      '--muted-foreground': '215 20% 68%',
      '--accent': '217.2 32.6% 17.5%',
      '--accent-foreground': '210 40% 98%',
      '--destructive': '0 70% 42%',
      '--destructive-foreground': '210 40% 98%',
      '--border': '217.2 32.6% 17.5%',
      '--input': '217 20% 46%',
      '--ring': '212.7 26.8% 83.9%',
      '--cta': '217 91% 60%',
      '--cta-foreground': '222 84% 5%',
      '--cta-hover': '217 91% 68%',
      '--accent-ink': '213 94% 72%',
      '--feature': '222 47% 16%',
      '--good-fg': '152 50% 64%',
      '--good-bg': '152 40% 13%',
      '--warn-fg': '40 85% 66%',
      '--warn-bg': '38 60% 13%',
      '--crit-fg': '0 85% 74%',
      '--crit-bg': '0 55% 15%',
      '--info-fg': '217 90% 76%',
      '--info-bg': '217 50% 15%',
      '--chart-1': '221 83% 53%',
      '--chart-2': '160 60% 45%',
      '--chart-3': '30 80% 55%',
      '--chart-4': '280 65% 60%',
      '--chart-5': '340 75% 55%',
      '--theme-accent': '217 91% 60%',
      '--theme-accent-light': '213 94% 72%',
      '--theme-accent-dark': '221 83% 53%',
      '--theme-surface': '222.2 84% 4.9%',
      '--theme-surface-light': '215 25% 27%',
    },
  },
  luxury: {
    name: 'luxury',
    label: 'Luxury',
    description: 'Premium gold and navy aesthetic with warm, elegant tones',
    previewColors: {
      primary: '#1a2340',
      accent: '#d4a24e',
      background: '#faf8f5',
    },
    light: {
      '--background': '40 33% 98%',
      '--foreground': '222 47% 11%',
      '--card': '40 33% 99%',
      '--card-foreground': '222 47% 11%',
      '--popover': '40 33% 99%',
      '--popover-foreground': '222 47% 11%',
      '--primary': '222 47% 11%',
      '--primary-foreground': '40 33% 98%',
      '--secondary': '35 25% 93%',
      '--secondary-foreground': '222 47% 11%',
      '--muted': '35 20% 94%',
      '--muted-foreground': '220 12% 38%',
      '--accent': '38 65% 60%',
      '--accent-foreground': '222 47% 11%',
      '--destructive': '0 72% 42%',
      '--destructive-foreground': '0 0% 100%',
      '--border': '35 20% 89%',
      '--input': '35 12% 54%',
      '--ring': '222 47% 11%',
      '--cta': '38 65% 60%',
      '--cta-foreground': '222 47% 11%',
      '--cta-hover': '38 65% 54%',
      '--accent-ink': '38 80% 27%',
      '--feature': '222 47% 11%',
      '--good-fg': '152 60% 22%',
      '--good-bg': '152 40% 91%',
      '--warn-fg': '30 90% 24%',
      '--warn-bg': '42 90% 89%',
      '--crit-fg': '0 70% 36%',
      '--crit-bg': '0 80% 96%',
      '--info-fg': '217 70% 34%',
      '--info-bg': '217 80% 95%',
      '--chart-1': '222 47% 25%',
      '--chart-2': '38 65% 60%',
      '--chart-3': '160 40% 45%',
      '--chart-4': '280 30% 55%',
      '--chart-5': '15 60% 55%',
      '--theme-accent': '38 65% 60%',
      '--theme-accent-light': '38 65% 75%',
      '--theme-accent-dark': '38 65% 45%',
      '--theme-surface': '222 47% 11%',
      '--theme-surface-light': '222 30% 25%',
    },
    dark: {
      '--background': '224 50% 6%',
      '--foreground': '38 25% 90%',
      '--card': '224 45% 9%',
      '--card-foreground': '38 25% 90%',
      '--popover': '224 45% 9%',
      '--popover-foreground': '38 25% 90%',
      '--primary': '38 25% 90%',
      '--primary-foreground': '224 50% 6%',
      '--secondary': '224 35% 15%',
      '--secondary-foreground': '38 25% 90%',
      '--muted': '224 35% 15%',
      '--muted-foreground': '220 15% 66%',
      '--accent': '38 65% 55%',
      '--accent-foreground': '224 50% 6%',
      '--destructive': '0 70% 42%',
      '--destructive-foreground': '0 0% 100%',
      '--border': '224 35% 15%',
      '--input': '224 20% 46%',
      '--ring': '38 65% 55%',
      '--cta': '38 65% 55%',
      '--cta-foreground': '224 50% 6%',
      '--cta-hover': '38 65% 62%',
      '--accent-ink': '38 70% 66%',
      '--feature': '230 50% 21%',
      '--good-fg': '152 50% 64%',
      '--good-bg': '152 40% 13%',
      '--warn-fg': '40 85% 66%',
      '--warn-bg': '38 60% 13%',
      '--crit-fg': '0 85% 74%',
      '--crit-bg': '0 55% 15%',
      '--info-fg': '217 90% 76%',
      '--info-bg': '217 50% 15%',
      '--chart-1': '38 65% 55%',
      '--chart-2': '160 50% 45%',
      '--chart-3': '222 40% 55%',
      '--chart-4': '280 45% 60%',
      '--chart-5': '15 65% 55%',
      '--theme-accent': '38 65% 55%',
      '--theme-accent-light': '38 65% 70%',
      '--theme-accent-dark': '38 65% 40%',
      '--theme-surface': '224 50% 6%',
      '--theme-surface-light': '224 35% 20%',
    },
  },
};

export function getThemePreset(name: string): ThemePreset {
  return THEME_PRESETS[name] ?? THEME_PRESETS[DEFAULT_THEME];
}

export function getAvailableThemes(): ThemePreset[] {
  return Object.values(THEME_PRESETS);
}

/**
 * Generate CSS variable declarations for a theme mode.
 * Used for server-side rendering to prevent flash of wrong theme.
 */
export function generateThemeCSS(themeName: string): string {
  const preset = getThemePreset(themeName);

  const lightVars = Object.entries(preset.light)
    .map(([key, value]) => `${key}: ${value};`)
    .join(' ');

  const darkVars = Object.entries(preset.dark)
    .map(([key, value]) => `${key}: ${value};`)
    .join(' ');

  return `:root { ${lightVars} } .dark { ${darkVars} }`;
}
