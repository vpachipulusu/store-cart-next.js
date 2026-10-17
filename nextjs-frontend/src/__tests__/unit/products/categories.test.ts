import { describe, expect, it } from 'vitest';
import { categoryName, toCategoryOptions, type CategoryRow } from '@/lib/products/categories';

const row = (id: string, name: string, parent: string | null, position = 0): CategoryRow => ({
  id,
  name,
  slug: name.toLowerCase(),
  parent_id: parent,
  position,
});

describe('toCategoryOptions', () => {
  it('orders depth-first by position then id, with the depth of each row', () => {
    const rows = [
      row('b', 'Mugs', null, 1),
      row('a', 'Clothing', null, 0),
      row('a2', 'Hats', 'a', 1),
      row('a1', 'Shirts', 'a', 0),
      row('a1x', 'Polo', 'a1', 0),
    ];
    expect(toCategoryOptions(rows, false)).toEqual([
      { id: 'a', label: 'Clothing', depth: 0 },
      { id: 'a1', label: 'Shirts', depth: 1 },
      { id: 'a1x', label: 'Polo', depth: 2 },
      { id: 'a2', label: 'Hats', depth: 1 },
      { id: 'b', label: 'Mugs', depth: 0 },
    ]);
  });

  it('shows a row whose parent is missing as a root instead of dropping it', () => {
    expect(toCategoryOptions([row('c', 'Orphan', 'gone')], false)).toEqual([
      { id: 'c', label: 'Orphan', depth: 0 },
    ]);
  });

  it('never loops on a parent cycle', () => {
    const options = toCategoryOptions([row('a', 'A', 'b'), row('b', 'B', 'a')], false);
    expect(options.length).toBeLessThanOrEqual(2);
  });

  it('lists a truncated set flat and sorted by name, without a tree', () => {
    const rows = [row('2', 'Zed', '1'), row('1', 'Alpha', null)];
    expect(toCategoryOptions(rows, true)).toEqual([
      { id: '1', label: 'Alpha', depth: 0 },
      { id: '2', label: 'Zed', depth: 0 },
    ]);
  });

  it('returns nothing for an empty list', () => {
    expect(toCategoryOptions([], false)).toEqual([]);
  });
});

describe('categoryName', () => {
  it('finds a name or returns null', () => {
    const rows = [row('a', 'Clothing', null)];
    expect(categoryName(rows, 'a')).toBe('Clothing');
    expect(categoryName(rows, 'z')).toBeNull();
  });
});
