export const siteConfig = {
  name: process.env.NEXT_PUBLIC_APP_NAME || 'SaaS Boilerplate',
  description: 'A modern SaaS boilerplate with Next.js 16, Prisma, Firebase Auth, and Stripe',
  url: process.env.NEXT_PUBLIC_APP_URL || 'http://localhost:3000',
  ogImage: '/og-image.png',
  links: {
    twitter: 'https://twitter.com/yourcompany',
    github: 'https://github.com/yourcompany/saas-boilerplate',
  },
};

export type SiteConfig = typeof siteConfig;
