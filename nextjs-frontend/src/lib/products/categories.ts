/**
 * Category display for the product screens (KAN-73 with KAN-246). Pure and safe for client code.
 *
 * The categories endpoint returns a flat list (roots first, then by parent, position, id). A tree is only built
 * from a complete list: when `truncated` is true a child's parent may be missing, so the list is shown flat.
 */

export type CategoryRow = {
  id: string;
  name: string;
  slug: string;
  parent_id: string | null;
  position: number;
};

/** The store's categories as the screens receive them. */
export type CategoryList = { rows: ReadonlyArray<CategoryRow>; truncated: boolean };

export type CategoryOption = { id: string; label: string; depth: number };

function byOrder(a: CategoryRow, b: CategoryRow): number {
  return a.position - b.position || a.id.localeCompare(b.id);
}

/** Depth-first options for a complete list; a flat, name-sorted list when truncated. */
export function toCategoryOptions(
  rows: ReadonlyArray<CategoryRow>,
  truncated: boolean
): CategoryOption[] {
  if (truncated) {
    return [...rows]
      .sort((a, b) => a.name.localeCompare(b.name) || a.id.localeCompare(b.id))
      .map((row) => ({ id: row.id, label: row.name, depth: 0 }));
  }
  const ids = new Set(rows.map((row) => row.id));
  const children = new Map<string | null, CategoryRow[]>();
  for (const row of rows) {
    // A parent that is not in the list is treated as a root, so no row is ever dropped.
    const parent = row.parent_id !== null && ids.has(row.parent_id) ? row.parent_id : null;
    children.set(parent, [...(children.get(parent) ?? []), row]);
  }
  const out: CategoryOption[] = [];
  const seen = new Set<string>();
  const visit = (parent: string | null, depth: number) => {
    for (const row of [...(children.get(parent) ?? [])].sort(byOrder)) {
      if (seen.has(row.id)) continue; // guards a parent cycle
      seen.add(row.id);
      out.push({ id: row.id, label: row.name, depth });
      visit(row.id, depth + 1);
    }
  };
  visit(null, 0);
  // Rows in a parent cycle have no root above them; list them flat rather than dropping them.
  for (const row of [...rows].sort(byOrder)) {
    if (seen.has(row.id)) continue;
    seen.add(row.id);
    out.push({ id: row.id, label: row.name, depth: 0 });
  }
  return out;
}

/** The name for an id, or null when the list does not hold it. */
export function categoryName(rows: ReadonlyArray<CategoryRow>, id: string): string | null {
  return rows.find((row) => row.id === id)?.name ?? null;
}
