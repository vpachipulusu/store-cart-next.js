/** Short UTC date for admin tables, e.g. "5 Jan 2026". */
export function formatAdminDate(value: string): string {
  if (Number.isNaN(Date.parse(value))) return '';
  return new Date(value).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  });
}

/** Short UTC date and time for audit entries, e.g. "5 Jan 2026, 14:03 UTC". */
export function formatAdminDateTime(value: string): string {
  if (Number.isNaN(Date.parse(value))) return '';
  const formatted = new Date(value).toLocaleString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'UTC',
  });
  return `${formatted} UTC`;
}
