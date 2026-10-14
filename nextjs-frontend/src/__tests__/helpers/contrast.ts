/** HSL triple ("38 65% 60%", fractions allowed) to WCAG 2.2 relative luminance. */
export function luminance(triple: string): number {
  const [h, s, l] = triple.replace(/%/g, '').trim().split(/\s+/).map(Number);
  const sat = s / 100;
  const light = l / 100;
  const k = (n: number) => (n + h / 30) % 12;
  const a = sat * Math.min(light, 1 - light);
  const channel = (n: number) =>
    light - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  const lin = (c: number) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
  return 0.2126 * lin(channel(0)) + 0.7152 * lin(channel(8)) + 0.0722 * lin(channel(4));
}

/** WCAG contrast ratio between two HSL triples. */
export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}
