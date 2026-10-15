/** Minimal HTML for the storefront route (KAN-64). Every dynamic value is escaped. */

const HTML_ESCAPES: Readonly<Record<string, string>> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
};

export function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => HTML_ESCAPES[char]);
}

export function renderDocument(
  title: string,
  heading: string,
  message: string,
  robots: 'index' | 'noindex'
): string {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="${robots}"><title>${escapeHtml(title)}</title></head><body style="font-family:system-ui,sans-serif;text-align:center;padding:4rem 1rem"><main><h1>${escapeHtml(heading)}</h1><p>${escapeHtml(message)}</p></main></body></html>`;
}
