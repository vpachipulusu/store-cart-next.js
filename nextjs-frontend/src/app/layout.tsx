import type { Metadata, Viewport } from 'next';
import './globals.css';
import { ThemeProvider } from '@/components/providers/theme-provider';
import { QueryProvider } from '@/components/providers/query-provider';
import { ToastProvider } from '@/components/providers/toast-provider';
import { cn } from '@/lib/utils';
import { getActiveTheme } from '@/app/actions/theme-actions';
import { getActiveFont } from '@/app/actions/font-actions';
import { generateThemeCSS } from '@/config/themes';
import { getFontById } from '@/config/fonts';

/**
 * Metadata Configuration
 * SEO and social media optimization
 */
export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_APP_URL || 'http://localhost:3000'),
  title: {
    default: 'Next.js Boilerplate',
    template: '%s | Next.js Boilerplate',
  },
  description: 'A modern Next.js 16 boilerplate with TypeScript, React 19, Tailwind CSS, and more',
  keywords: ['Next.js', 'React', 'TypeScript', 'Tailwind CSS', 'Boilerplate', 'Starter'],
  authors: [
    {
      name: 'Your Name',
      url: 'https://yourwebsite.com',
    },
  ],
  creator: 'Your Name',
  openGraph: {
    type: 'website',
    locale: 'en_US',
    url: 'https://yourwebsite.com',
    title: 'Next.js Boilerplate',
    description:
      'A modern Next.js 16 boilerplate with TypeScript, React 19, Tailwind CSS, and more',
    siteName: 'Next.js Boilerplate',
    images: [
      {
        url: '/og-image.png',
        width: 1200,
        height: 630,
        alt: 'Next.js Boilerplate',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Next.js Boilerplate',
    description:
      'A modern Next.js 16 boilerplate with TypeScript, React 19, Tailwind CSS, and more',
    images: ['/og-image.png'],
    creator: '@yourusername',
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      'max-video-preview': -1,
      'max-image-preview': 'large',
      'max-snippet': -1,
    },
  },
  icons: {
    icon: [
      { url: '/favicon.ico' },
      { url: '/favicon-16x16.png', sizes: '16x16', type: 'image/png' },
      { url: '/favicon-32x32.png', sizes: '32x32', type: 'image/png' },
    ],
    apple: [{ url: '/apple-touch-icon.png' }],
  },
  manifest: '/site.webmanifest',
};

/**
 * Viewport Configuration
 * Responsive design and PWA settings
 */
export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  maximumScale: 5,
  userScalable: true,
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#faf8f5' },
    { media: '(prefers-color-scheme: dark)', color: '#0b1120' },
  ],
};

/**
 * Root Layout Component
 *
 * Main layout wrapper for the entire application
 * Includes all providers and global configurations
 *
 * Features:
 * - Theme provider for dark/light mode
 * - React Query provider for data fetching
 * - Toast provider for notifications
 * - Font optimization with next/font
 * - Proper HTML semantics and accessibility
 *
 * @param children - Page content
 */
export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const [activeTheme, activeFontId] = await Promise.all([getActiveTheme(), getActiveFont()]);

  const { font: activeFont } = getFontById(activeFontId);

  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <style dangerouslySetInnerHTML={{ __html: generateThemeCSS(activeTheme) }} />
      </head>
      <body
        className={cn(activeFont.variable, 'min-h-screen bg-background font-sans antialiased')}
        suppressHydrationWarning
      >
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange={false}
          appTheme={activeTheme}
        >
          <QueryProvider>
            <ToastProvider>
              <div className="relative flex min-h-screen flex-col">
                <div className="flex-1">{children}</div>
              </div>
            </ToastProvider>
          </QueryProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
