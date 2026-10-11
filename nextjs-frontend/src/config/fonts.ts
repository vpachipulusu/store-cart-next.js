/**
 * Font Configuration
 *
 * Centralized font management for the application
 * Fonts are loaded from Google Fonts and configured via admin settings
 */

import {
  Inter,
  Open_Sans,
  Roboto,
  Lato,
  Poppins,
  Nunito,
  Work_Sans,
  Source_Sans_3,
  Montserrat,
  Raleway,
} from 'next/font/google';

/**
 * Font loader instances
 * Must be called at module scope as required by Next.js
 */
const interFont = Inter({
  subsets: ['latin'],
  variable: '--font-body',
  display: 'swap',
});

const openSansFont = Open_Sans({
  subsets: ['latin'],
  variable: '--font-body',
  display: 'swap',
});

const robotoFont = Roboto({
  subsets: ['latin'],
  weight: ['300', '400', '500', '700'],
  variable: '--font-body',
  display: 'swap',
});

const latoFont = Lato({
  subsets: ['latin'],
  weight: ['300', '400', '700'],
  variable: '--font-body',
  display: 'swap',
});

const poppinsFont = Poppins({
  subsets: ['latin'],
  weight: ['300', '400', '500', '600', '700'],
  variable: '--font-body',
  display: 'swap',
});

const nunitoFont = Nunito({
  subsets: ['latin'],
  variable: '--font-body',
  display: 'swap',
});

const workSansFont = Work_Sans({
  subsets: ['latin'],
  variable: '--font-body',
  display: 'swap',
});

const sourceSansFont = Source_Sans_3({
  subsets: ['latin'],
  variable: '--font-body',
  display: 'swap',
});

const montserratFont = Montserrat({
  subsets: ['latin'],
  variable: '--font-body',
  display: 'swap',
});

const ralewayFont = Raleway({
  subsets: ['latin'],
  variable: '--font-body',
  display: 'swap',
});

/**
 * Available font configurations
 * All fonts are popular, highly readable, and optimized for web use
 */
export const AVAILABLE_FONTS = {
  inter: {
    id: 'inter',
    name: 'Inter',
    description: 'Modern, clean sans-serif. Excellent for UI and reading.',
    font: interFont,
    category: 'sans-serif',
  },
  opensans: {
    id: 'opensans',
    name: 'Open Sans',
    description: 'Humanist sans-serif. Friendly and neutral.',
    font: openSansFont,
    category: 'sans-serif',
  },
  roboto: {
    id: 'roboto',
    name: 'Roboto',
    description: "Google's signature font. Clean and modern.",
    font: robotoFont,
    category: 'sans-serif',
  },
  lato: {
    id: 'lato',
    name: 'Lato',
    description: 'Semi-rounded sans-serif. Warm and stable.',
    font: latoFont,
    category: 'sans-serif',
  },
  poppins: {
    id: 'poppins',
    name: 'Poppins',
    description: 'Geometric sans-serif. Modern and friendly.',
    font: poppinsFont,
    category: 'sans-serif',
  },
  nunito: {
    id: 'nunito',
    name: 'Nunito',
    description: 'Rounded sans-serif. Soft and approachable.',
    font: nunitoFont,
    category: 'sans-serif',
  },
  worksans: {
    id: 'worksans',
    name: 'Work Sans',
    description: 'Optimized for screen display. Professional.',
    font: workSansFont,
    category: 'sans-serif',
  },
  sourcesans: {
    id: 'sourcesans',
    name: 'Source Sans 3',
    description: "Adobe's sans-serif. Clear and readable.",
    font: sourceSansFont,
    category: 'sans-serif',
  },
  montserrat: {
    id: 'montserrat',
    name: 'Montserrat',
    description: 'Urban, geometric sans-serif. Bold and modern.',
    font: montserratFont,
    category: 'sans-serif',
  },
  raleway: {
    id: 'raleway',
    name: 'Raleway',
    description: 'Elegant sans-serif. Sophisticated and clean.',
    font: ralewayFont,
    category: 'sans-serif',
  },
} as const;

export type FontId = keyof typeof AVAILABLE_FONTS;

/**
 * Default font ID
 */
export const DEFAULT_FONT: FontId = 'inter';

/**
 * Get font configuration by ID
 */
export function getFontById(fontId: string): (typeof AVAILABLE_FONTS)[FontId] {
  const id = fontId as FontId;
  return AVAILABLE_FONTS[id] || AVAILABLE_FONTS[DEFAULT_FONT];
}

/**
 * Get all font options for selection
 */
export function getFontOptions() {
  return Object.values(AVAILABLE_FONTS).map((font) => ({
    id: font.id,
    name: font.name,
    description: font.description,
    category: font.category,
  }));
}
