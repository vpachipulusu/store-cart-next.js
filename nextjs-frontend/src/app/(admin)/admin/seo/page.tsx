import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { db } from '@/lib/db/client';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Plus, MoreHorizontal, Edit, Trash2, RefreshCw, ExternalLink } from 'lucide-react';
import { AddMetaDialog } from '@/components/admin/add-meta-dialog';
import { AddRedirectDialog } from '@/components/admin/add-redirect-dialog';

async function getSEOData() {
  try {
    const metaTags = await db.sEOMeta.findMany({
      orderBy: { page: 'asc' },
    });

    const redirects = await db.uRLRedirect.findMany({
      orderBy: { createdAt: 'desc' },
    });

    return {
      metaTags,
      redirects,
    };
  } catch (error) {
    console.error('Error fetching SEO data:', error);
    return {
      metaTags: [],
      redirects: [],
    };
  }
}

export default async function AdminSEOPage() {
  const data = await getSEOData();

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">SEO Management</h1>
        <p className="text-muted-foreground">Manage meta tags, redirects, and SEO configuration</p>
      </div>

      {/* SEO Tabs */}
      <Tabs defaultValue="meta-tags" className="space-y-6">
        <TabsList className="grid w-full max-w-md grid-cols-3">
          <TabsTrigger value="meta-tags">Meta Tags</TabsTrigger>
          <TabsTrigger value="redirects">Redirects</TabsTrigger>
          <TabsTrigger value="sitemap">Sitemap</TabsTrigger>
        </TabsList>

        {/* Meta Tags */}
        <TabsContent value="meta-tags" className="space-y-4">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>Page Meta Tags</CardTitle>
                  <CardDescription>Configure SEO meta tags for each page</CardDescription>
                </div>
                <AddMetaDialog />
              </div>
            </CardHeader>
            <CardContent>
              {data.metaTags.length > 0 ? (
                <div className="rounded-lg border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Page</TableHead>
                        <TableHead>Title</TableHead>
                        <TableHead>Description</TableHead>
                        <TableHead>Index</TableHead>
                        <TableHead className="text-right">Actions</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.metaTags.map((meta: any) => (
                        <TableRow key={meta.id}>
                          <TableCell className="font-mono text-sm font-semibold">
                            {meta.page}
                          </TableCell>
                          <TableCell className="max-w-xs truncate font-medium">
                            {meta.title}
                          </TableCell>
                          <TableCell className="max-w-md truncate text-sm text-muted-foreground">
                            {meta.description}
                          </TableCell>
                          <TableCell>
                            {meta.noindex ? (
                              <Badge variant="destructive">No Index</Badge>
                            ) : (
                              <Badge variant="default">Indexed</Badge>
                            )}
                          </TableCell>
                          <TableCell className="text-right">
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <Button variant="ghost" className="h-8 w-8 p-0">
                                  <span className="sr-only">Open menu</span>
                                  <MoreHorizontal className="h-4 w-4" />
                                </Button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end">
                                <DropdownMenuLabel>Actions</DropdownMenuLabel>
                                <DropdownMenuSeparator />
                                <DropdownMenuItem>
                                  <Edit className="mr-2 h-4 w-4" />
                                  Edit Meta Tags
                                </DropdownMenuItem>
                                <DropdownMenuItem>
                                  <ExternalLink className="mr-2 h-4 w-4" />
                                  Preview Page
                                </DropdownMenuItem>
                                <DropdownMenuSeparator />
                                <DropdownMenuItem className="text-destructive focus:text-destructive">
                                  <Trash2 className="mr-2 h-4 w-4" />
                                  Delete
                                </DropdownMenuItem>
                              </DropdownMenuContent>
                            </DropdownMenu>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center rounded-lg border border-dashed py-12">
                  <p className="text-sm font-medium text-muted-foreground">
                    No meta tags configured
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Add pages to get started with SEO optimization
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* URL Redirects */}
        <TabsContent value="redirects" className="space-y-4">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>URL Redirects</CardTitle>
                  <CardDescription>Manage 301/302 redirects for old URLs</CardDescription>
                </div>
                <AddRedirectDialog />
              </div>
            </CardHeader>
            <CardContent>
              {data.redirects.length > 0 ? (
                <div className="rounded-lg border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>From</TableHead>
                        <TableHead>To</TableHead>
                        <TableHead>Type</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead className="text-right">Actions</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.redirects.map((redirect: any) => (
                        <TableRow key={redirect.id}>
                          <TableCell className="font-mono text-sm">{redirect.fromPath}</TableCell>
                          <TableCell className="font-mono text-sm text-muted-foreground">
                            {redirect.toPath}
                          </TableCell>
                          <TableCell>
                            <Badge variant="outline" className="font-mono">
                              {redirect.statusCode}
                            </Badge>
                          </TableCell>
                          <TableCell>
                            {redirect.enabled ? (
                              <Badge variant="default">Enabled</Badge>
                            ) : (
                              <Badge variant="secondary">Disabled</Badge>
                            )}
                          </TableCell>
                          <TableCell className="text-right">
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <Button variant="ghost" className="h-8 w-8 p-0">
                                  <span className="sr-only">Open menu</span>
                                  <MoreHorizontal className="h-4 w-4" />
                                </Button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end">
                                <DropdownMenuLabel>Actions</DropdownMenuLabel>
                                <DropdownMenuSeparator />
                                <DropdownMenuItem>
                                  <Edit className="mr-2 h-4 w-4" />
                                  Edit Redirect
                                </DropdownMenuItem>
                                <DropdownMenuItem>
                                  <ExternalLink className="mr-2 h-4 w-4" />
                                  Test Redirect
                                </DropdownMenuItem>
                                <DropdownMenuSeparator />
                                <DropdownMenuItem className="text-destructive focus:text-destructive">
                                  <Trash2 className="mr-2 h-4 w-4" />
                                  Delete
                                </DropdownMenuItem>
                              </DropdownMenuContent>
                            </DropdownMenu>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center rounded-lg border border-dashed py-12">
                  <p className="text-sm font-medium text-muted-foreground">
                    No redirects configured
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Add URL redirects to manage old or changed URLs
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Sitemap */}
        <TabsContent value="sitemap" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Sitemap Management</CardTitle>
              <CardDescription>Generate and manage XML sitemaps for search engines</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="flex items-center justify-between rounded-xl border bg-accent/5 p-4">
                <div className="space-y-1">
                  <p className="font-semibold">sitemap.xml</p>
                  <p className="text-sm text-muted-foreground">
                    Last generated: {new Date().toLocaleString()}
                  </p>
                </div>
                <Button variant="outline">
                  <RefreshCw className="mr-2 h-4 w-4" />
                  Regenerate
                </Button>
              </div>

              <div className="space-y-2.5">
                <Label htmlFor="sitemap-url" className="text-sm font-semibold">
                  Sitemap URL
                </Label>
                <div className="flex gap-2">
                  <Input
                    id="sitemap-url"
                    readOnly
                    value="https://yourapp.com/sitemap.xml"
                    className="font-mono"
                  />
                  <Button variant="outline" size="icon">
                    <ExternalLink className="h-4 w-4" />
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  Submit this URL to Google Search Console and Bing Webmaster Tools
                </p>
              </div>

              <div className="space-y-3">
                <Label className="text-sm font-semibold">Sitemap Statistics</Label>
                <div className="grid gap-4 md:grid-cols-3">
                  <div className="rounded-lg border p-4">
                    <p className="text-2xl font-bold">0</p>
                    <p className="text-xs text-muted-foreground">Total URLs</p>
                  </div>
                  <div className="rounded-lg border p-4">
                    <p className="text-2xl font-bold">0 KB</p>
                    <p className="text-xs text-muted-foreground">File Size</p>
                  </div>
                  <div className="rounded-lg border p-4">
                    <p className="text-2xl font-bold">Never</p>
                    <p className="text-xs text-muted-foreground">Last Submitted</p>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
