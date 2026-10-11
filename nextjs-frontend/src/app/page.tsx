import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ArrowRight, Code, Zap, Shield, Rocket } from 'lucide-react';

export default function HomePage() {
  return (
    <div className="container relative">
      {/* Hero Section */}
      <section className="mx-auto flex max-w-[980px] flex-col items-center gap-4 py-16 md:py-24 lg:py-32">
        <div className="stagger-children flex flex-col items-center gap-4">
          <div className="flex items-center gap-2 rounded-full border border-theme-accent/30 px-4 py-1.5 text-sm text-theme-accent-dark dark:text-theme-accent-light">
            <Rocket className="h-4 w-4" />
            <span>Next.js 16 + React 19 + TypeScript</span>
          </div>
          <h1 className="text-center text-4xl leading-tight tracking-tight md:text-6xl lg:text-7xl lg:leading-[1.05]">
            Build modern web apps
            <br className="hidden sm:inline" />
            <span className="text-gradient-accent"> faster than ever</span>
          </h1>
          <p className="max-w-[700px] text-balance text-center text-lg leading-relaxed text-muted-foreground sm:text-xl">
            A production-ready boilerplate with everything you need to build amazing applications.
            TypeScript, Tailwind CSS, Prisma, and more.
          </p>
          <div className="flex w-full items-center justify-center space-x-4 py-4 md:pb-10">
            <Button
              size="lg"
              asChild
              className="bg-theme-accent text-white shadow-lg shadow-theme-accent/25 hover:bg-theme-accent-dark"
            >
              <Link href="/signup">
                Get Started
                <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
            </Button>
            <Button size="lg" variant="outline" asChild className="theme-border">
              <Link
                href="https://github.com/yourusername/your-repo"
                target="_blank"
                rel="noopener noreferrer"
              >
                View on GitHub
              </Link>
            </Button>
          </div>
        </div>
      </section>

      <div className="divider-accent mx-auto max-w-[600px]" />

      {/* Features Section */}
      <section className="mx-auto max-w-[1200px] py-16 md:py-20">
        <div className="mb-12 text-center">
          <h2 className="text-3xl tracking-tight md:text-4xl">
            Everything you need
          </h2>
          <p className="mt-3 text-lg text-muted-foreground">
            Built with best practices, ready for production
          </p>
        </div>
        <div className="stagger-children grid grid-cols-1 gap-8 md:grid-cols-2 lg:grid-cols-4">
          <Card className="theme-card">
            <CardHeader>
              <div className="mb-4 h-px w-12 bg-gradient-to-r from-theme-accent to-transparent" />
              <Code className="mb-2 h-8 w-8 text-theme-accent" />
              <CardTitle className="text-lg">Type Safe</CardTitle>
              <CardDescription>
                Built with TypeScript for full type safety and better developer experience
              </CardDescription>
            </CardHeader>
          </Card>

          <Card className="theme-card">
            <CardHeader>
              <div className="mb-4 h-px w-12 bg-gradient-to-r from-theme-accent to-transparent" />
              <Zap className="mb-2 h-8 w-8 text-theme-accent" />
              <CardTitle className="text-lg">Blazing Fast</CardTitle>
              <CardDescription>
                Optimized with Next.js 16 App Router and React 19 for lightning fast performance
              </CardDescription>
            </CardHeader>
          </Card>

          <Card className="theme-card">
            <CardHeader>
              <div className="mb-4 h-px w-12 bg-gradient-to-r from-theme-accent to-transparent" />
              <Shield className="mb-2 h-8 w-8 text-theme-accent" />
              <CardTitle className="text-lg">Secure by Default</CardTitle>
              <CardDescription>
                Firebase Auth integration with multiple authentication providers
              </CardDescription>
            </CardHeader>
          </Card>

          <Card className="theme-card">
            <CardHeader>
              <div className="mb-4 h-px w-12 bg-gradient-to-r from-theme-accent to-transparent" />
              <Rocket className="mb-2 h-8 w-8 text-theme-accent" />
              <CardTitle className="text-lg">Production Ready</CardTitle>
              <CardDescription>
                Pre-configured with testing, linting, formatting, and deployment setup
              </CardDescription>
            </CardHeader>
          </Card>
        </div>
      </section>

      <div className="divider-accent mx-auto max-w-[600px]" />

      {/* Tech Stack Section */}
      <section className="mx-auto max-w-[980px] py-16 md:py-20">
        <h2 className="mb-8 text-center text-3xl tracking-tight md:text-4xl">
          Powered by Modern Technologies
        </h2>
        <Card className="theme-card">
          <CardHeader>
            <CardTitle>What&apos;s Included</CardTitle>
            <CardDescription>
              Everything you need to build production-ready applications
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <TechItem name="Next.js 16" description="App Router with Server Components" />
              <TechItem name="React 19" description="Latest features and optimizations" />
              <TechItem name="TypeScript" description="Type-safe development" />
              <TechItem name="Tailwind CSS" description="Utility-first styling" />
              <TechItem name="Prisma" description="Type-safe database ORM" />
              <TechItem name="Firebase Auth" description="Authentication made easy" />
              <TechItem name="React Query" description="Powerful data fetching" />
              <TechItem name="Zod" description="Schema validation" />
              <TechItem name="Vitest" description="Fast unit testing" />
              <TechItem name="Playwright" description="End-to-end testing" />
              <TechItem name="ESLint + Prettier" description="Code quality tools" />
              <TechItem name="Capacitor" description="Native mobile support" />
            </div>
          </CardContent>
        </Card>
      </section>

      {/* CTA Section */}
      <section className="mx-auto max-w-[980px] py-8 md:py-12 lg:py-24">
        <Card className="border-0 bg-gradient-to-br from-theme-surface to-theme-surface-light text-white dark:border dark:border-theme-accent/20 dark:from-theme-accent/[0.08] dark:to-theme-accent/[0.02]">
          <CardHeader className="py-16 text-center">
            <CardTitle className="text-3xl text-white dark:text-foreground">
              Ready to start building?
            </CardTitle>
            <CardDescription className="text-lg text-white/70 dark:text-muted-foreground">
              Get started with this boilerplate and ship your next project faster
            </CardDescription>
          </CardHeader>
          <CardContent className="flex justify-center pb-16">
            <Button
              size="lg"
              asChild
              className="bg-theme-accent text-white shadow-lg shadow-theme-accent/25 hover:bg-theme-accent-dark"
            >
              <Link href="/signup">
                Create an Account
                <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
            </Button>
          </CardContent>
        </Card>
      </section>
    </div>
  );
}

function TechItem({ name, description }: { name: string; description: string }) {
  return (
    <div className="flex flex-col space-y-1 border-l-2 border-theme-accent/30 pl-4">
      <p className="font-semibold">{name}</p>
      <p className="text-sm text-muted-foreground">{description}</p>
    </div>
  );
}
