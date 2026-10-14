import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Send } from 'lucide-react';

export const metadata = {
  title: 'Contact Us',
  description: 'Get in touch with our team',
};

export default async function ContactPage({
  searchParams,
}: {
  searchParams: Promise<{ plan?: string }>;
}) {
  const params = await searchParams;
  const selectedPlan = params.plan;

  return (
    <div className="min-h-screen px-4 py-12">
      <div className="mx-auto max-w-5xl">
        {/* Header */}
        <div className="mb-12 text-center">
          <h1 className="mb-4 text-4xl tracking-tight">Contact Us</h1>
          <p className="mx-auto max-w-2xl text-xl text-muted-foreground">
            A support contact is coming soon. Messages cannot be sent from this page yet.
          </p>
          {selectedPlan && (
            <p className="mt-4 text-sm text-primary">
              Interested in the {selectedPlan.charAt(0).toUpperCase() + selectedPlan.slice(1)} plan
            </p>
          )}
        </div>

        <div className="grid gap-8 md:grid-cols-3">
          {/* Contact Form */}
          <div className="md:col-span-2">
            <Card>
              <CardHeader>
                <CardTitle>Send us a message</CardTitle>
                <CardDescription>
                  This form is unavailable and does not send messages.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <fieldset disabled aria-label="Contact form unavailable" className="space-y-6">
                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="space-y-2">
                      <Label htmlFor="firstName">First Name</Label>
                      <Input id="firstName" placeholder="John" required />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="lastName">Last Name</Label>
                      <Input id="lastName" placeholder="Doe" required />
                    </div>
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="email">Email</Label>
                    <Input id="email" type="email" placeholder="Your email address" required />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="company">Company (Optional)</Label>
                    <Input id="company" placeholder="Acme Inc." />
                  </div>

                  {selectedPlan && (
                    <div className="space-y-2">
                      <Label htmlFor="plan">Interested Plan</Label>
                      <Input
                        id="plan"
                        defaultValue={selectedPlan.charAt(0).toUpperCase() + selectedPlan.slice(1)}
                        readOnly
                        className="bg-muted"
                      />
                    </div>
                  )}

                  <div className="space-y-2">
                    <Label htmlFor="subject">Subject</Label>
                    <Input
                      id="subject"
                      placeholder={
                        selectedPlan ? `Inquiry about ${selectedPlan} plan` : 'How can we help you?'
                      }
                      required
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="message">Message</Label>
                    <Textarea
                      id="message"
                      placeholder="Tell us more about your needs..."
                      rows={6}
                      required
                    />
                  </div>

                  <Button
                    type="button"
                    disabled
                    size="lg"
                    variant="accent" className="w-full"
                  >
                    <Send className="mr-2 h-4 w-4" />
                    Send Message
                  </Button>

                  <p className="text-center text-sm text-muted-foreground">
                    Message sending is coming soon.
                  </p>
                </fieldset>
              </CardContent>
            </Card>
          </div>

          {/* Support availability */}
          <div>
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Support Contact</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">
                  A support contact is coming soon. Email, phone and sales channels are not
                  available yet.
                </p>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}
