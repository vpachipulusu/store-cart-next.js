# SaaS Boilerplate - Next.js 16

A production-ready SaaS boilerplate built with Next.js 16, React 19, Prisma, Firebase Auth, Stripe, and comprehensive testing.

## ⚡ Quick Start

```bash
# Install dependencies
npm install

# Setup environment
cp .env.example .env
# Edit .env with your credentials (see GUIDE.md)

# Initialize database
npx prisma generate
npx prisma db push

# Start development
npm run dev
```

Visit `http://localhost:3000`

📖 **[Read the Complete Guide](GUIDE.md)** for detailed setup, features, and troubleshooting.

## ✨ Features

### Customer Features

- 🔐 **Authentication** - Email/password + OAuth (Google, GitHub)
- 👤 **User Dashboard** - Stats, activity, notifications
- ⚙️ **Profile & Settings** - Customizable preferences
- 🔒 **Security** - Password change, 2FA, login history
- 💳 **Subscriptions** - Stripe integration with 3 tiers

### Admin Features

- 📊 **Admin Dashboard** - User metrics, revenue, analytics
- 👥 **User Management** - Search, filter, edit, delete users
- 💰 **Subscription Management** - View, cancel, refund subscriptions
- 📈 **Analytics** - Charts, reports, insights
- 🔍 **SEO Tools** - Meta tags, redirects
- 🛠️ **Settings** - Feature flags, email templates
- 📝 **Audit Logs** - Track all admin actions

### Developer Features

- ⚡ Next.js 16 App Router with Server Components
- 🎨 shadcn/ui + Tailwind CSS
- 🗄️ Prisma ORM + PostgreSQL
- 🧪 Vitest + Playwright testing
- 📱 Mobile-ready (PWA + Capacitor)
- 🚀 Vercel-optimized

## 🏗️ Tech Stack

- **Frontend:** Next.js 16, React 19, TypeScript, Tailwind CSS v4
- **Backend:** Next.js API Routes, Server Actions, Prisma ORM v6
- **Database:** PostgreSQL
- **Auth:** Firebase Authentication
- **Payments:** Stripe
- **Testing:** Vitest, Playwright, React Testing Library
- **Mobile:** Capacitor v6

## 📚 Documentation

- **[Complete Guide](GUIDE.md)** - Full documentation with setup, features, and troubleshooting
- **[Environment Variables](#environment-variables)** - Required configuration

## 🔑 Environment Variables

```env
# Database
DATABASE_URL="postgresql://..."

# Firebase
NEXT_PUBLIC_FIREBASE_API_KEY="..."
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN="..."
NEXT_PUBLIC_FIREBASE_PROJECT_ID="..."
FIREBASE_PROJECT_ID="..."
FIREBASE_CLIENT_EMAIL="..."
FIREBASE_PRIVATE_KEY="..."

# Stripe
STRIPE_SECRET_KEY="sk_test_..."
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY="pk_test_..."
STRIPE_WEBHOOK_SECRET="whsec_..."
STRIPE_PRICE_ID_PRO_MONTHLY="price_..."
STRIPE_PRICE_ID_PRO_YEARLY="price_..."
```

See [GUIDE.md](GUIDE.md) for detailed setup instructions.

## 🚀 Commands

```bash
npm run dev              # Start development server
npm run build            # Build for production
npm run start            # Start production server
npm run lint             # Run ESLint
npm run test             # Run all tests
npm run test:unit        # Run unit tests
npm run test:e2e         # Run E2E tests
npm run prisma:studio    # Open Prisma Studio
```

## 🏢 Project Structure

```
src/
├── app/
│   ├── (auth)/          # Login, signup, password reset
│   ├── (admin)/admin/   # Admin portal (8 pages)
│   ├── dashboard/       # Customer dashboard
│   ├── pricing/         # Smart pricing page
│   ├── contact/         # Contact form
│   ├── actions/         # Server Actions
│   └── api/             # API routes + webhooks
├── components/
│   ├── ui/              # shadcn/ui components
│   ├── auth/            # Auth forms
│   ├── pricing/         # Pricing components
│   └── providers/       # React providers
├── lib/
│   ├── db/              # Prisma client
│   ├── firebase/        # Firebase setup
│   ├── stripe/          # Stripe integration
│   ├── services/        # Audit logging, etc.
│   └── utils/           # Utilities
└── proxy.ts             # Middleware (auth, rate limiting)
```

## 🛠️ Common Issues

### Lock File Error

```bash
npm run dev:kill    # Kills processes and removes lock
npm run dev         # Start fresh
```

### Module Not Found

This project uses **npm** (not pnpm):

```bash
rm -rf node_modules package-lock.json
npm install
```

### Database Issues

```bash
npx prisma generate
npx prisma db push
```

See [GUIDE.md](GUIDE.md) for more troubleshooting.

## 📦 What's Included

### Pages

- Landing page
- Authentication (login, signup, password reset, email verification)
- Customer dashboard (profile, settings, security)
- Admin portal (8 pages: dashboard, users, subscriptions, analytics, SEO, settings, audit logs)
- Pricing page with smart CTAs
- Contact form

### Database Models

- User, UserSettings, LoginHistory, Notification
- AdminUser, AuditLog
- Subscription data (via Stripe)
- SEOMeta, URLRedirect, AppSettings, FeatureFlag, EmailTemplate

### Features Implemented

- ✅ Complete authentication flow
- ✅ Customer dashboard with analytics
- ✅ Full admin portal with 8 pages
- ✅ Subscription management with Stripe
- ✅ Smart pricing page (detects auth state)
- ✅ Login history tracking
- ✅ Audit logging for admin actions
- ✅ Email verification enforcement
- ✅ Password change functionality
- ✅ Data export (GDPR compliance)
- ✅ Account deletion
- ✅ Rate limiting middleware
- ✅ Security headers
- ✅ SEO management tools

## 📄 License

MIT

## 🤝 Contributing

Contributions welcome! Please read the [GUIDE.md](GUIDE.md) first.

## 📞 Support

For detailed documentation, setup instructions, and troubleshooting, see **[GUIDE.md](GUIDE.md)**.
