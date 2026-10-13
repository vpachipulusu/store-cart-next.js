import type { MetadataRoute } from 'next';
import { siteConfig } from '@/config/site';

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: siteConfig.name,
    short_name: siteConfig.name,
    description: siteConfig.description,
    start_url: '/',
    display: 'standalone',
    background_color: '#ffffff',
    theme_color: '#000000',
    icons: [
      { src: '/icon-192.png.svg', sizes: '192x192', type: 'image/svg+xml' },
      { src: '/icon-512.png.svg', sizes: '512x512', type: 'image/svg+xml' },
    ],
  };
}
