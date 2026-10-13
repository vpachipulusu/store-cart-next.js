/**
 * Single source of truth for brand strings. Everything that needs the app name,
 * description, URL or support email (metadata, manifest, TOTP issuer, logger,
 * admin settings, seed scripts) reads it from here.
 */
export const siteConfig = {
  name: process.env.NEXT_PUBLIC_APP_NAME || 'StoreCart',
  description: 'A modern Next.js 16 boilerplate with TypeScript, React 19, Tailwind CSS, and more',
  keywords: ['Next.js', 'React', 'TypeScript', 'Tailwind CSS', 'Boilerplate', 'Starter'],
  url: process.env.NEXT_PUBLIC_APP_URL || 'http://localhost:3000',
  supportEmail: process.env.NEXT_PUBLIC_SUPPORT_EMAIL || 'support@example.com',
  ogImage: '/og-image.png',
};

export type SiteConfig = typeof siteConfig;
