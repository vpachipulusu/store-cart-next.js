/** KAN-74: the CSV file rules shared by the import dialog and the server action. */
import { describe, expect, it } from 'vitest';
import {
  csvFileError,
  csvFileSchema,
  EMPTY_FILE_MESSAGE,
  IMPORT_COLUMNS,
  issueLocation,
  MAX_IMPORT_BYTES,
  NO_FILE_MESSAGE,
  SAMPLE_CSV,
  TOO_LARGE_MESSAGE,
  WRONG_TYPE_MESSAGE,
} from '@/lib/products/csv-import';

const file = (name: string, type: string, size: number) => ({ name, type, size });

describe('csvFileError', () => {
  it.each(['text/csv', 'application/vnd.ms-excel', '', 'text/plain', 'application/csv'])(
    'accepts a .csv file reported as %j',
    (type) => {
      expect(csvFileError(file('products.CSV', type, 10))).toBeNull();
    }
  );

  it.each([
    [file('products.xlsx', 'text/csv', 10), WRONG_TYPE_MESSAGE],
    [file('products.csv', 'application/pdf', 10), WRONG_TYPE_MESSAGE],
    [file('products.csv', 'text/csv', 0), EMPTY_FILE_MESSAGE],
    [file('products.csv', 'text/csv', MAX_IMPORT_BYTES + 1), TOO_LARGE_MESSAGE],
  ])('rejects %j', (input, message) => {
    expect(csvFileError(input)).toBe(message);
  });

  it('accepts a file exactly at the cap', () => {
    expect(csvFileError(file('p.csv', 'text/csv', MAX_IMPORT_BYTES))).toBeNull();
  });
});

describe('csvFileSchema', () => {
  it('parses a valid File', () => {
    const csv = new File(['title,sku,price_minor\n'], 'p.csv', { type: 'text/csv' });
    expect(csvFileSchema.safeParse(csv).success).toBe(true);
  });

  it.each([null, 'title,sku', { name: 'p.csv', size: 3, type: 'text/csv' }])(
    'rejects %j as no file',
    (value) => {
      const parsed = csvFileSchema.safeParse(value);
      expect(parsed.success).toBe(false);
      expect(parsed.error?.issues[0]?.message).toBe(NO_FILE_MESSAGE);
    }
  );

  it('carries the file rule message', () => {
    const parsed = csvFileSchema.safeParse(new File([''], 'p.csv', { type: 'text/csv' }));
    expect(parsed.error?.issues[0]?.message).toBe(EMPTY_FILE_MESSAGE);
  });
});

describe('issueLocation', () => {
  it('names the row, or the whole file', () => {
    expect(issueLocation({ row: 4, column: 'sku', message: 'x' })).toBe('Row 4');
    expect(issueLocation({ row: null, column: null, message: 'x' })).toBe('Whole file');
  });
});

describe('SAMPLE_CSV', () => {
  it('has every column in order and rows of the same width without formula cells', () => {
    const [header, ...rows] = SAMPLE_CSV.trim().split('\n');
    expect(header).toBe(IMPORT_COLUMNS.join(','));
    for (const row of rows) {
      const cells = row.split(',');
      expect(cells).toHaveLength(IMPORT_COLUMNS.length);
      for (const cell of cells) expect(cell).not.toMatch(/^\s*[=+\-@]/);
    }
  });
});
