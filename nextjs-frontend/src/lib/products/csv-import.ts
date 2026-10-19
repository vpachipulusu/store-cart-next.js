import { z } from 'zod';

/**
 * Product CSV import rules (KAN-74). Pure, so the import dialog (before any request) and the server action share
 * one definition. The limits mirror the backend (`app/services/product_import.py`: 1,000,000 bytes, 500 rows,
 * UTF-8); the backend stays the authority and checks every row and cell.
 */
export const MAX_IMPORT_BYTES = 1_000_000;
export const MAX_IMPORT_ROWS = 500;

export const IMPORT_COLUMNS = [
  'title',
  'slug',
  'description',
  'status',
  'sku',
  'price_minor',
  'compare_at_price_minor',
  'weight_grams',
  'stock',
] as const;

export const CSV_ACCEPT = '.csv,text/csv';

export const NO_FILE_MESSAGE = 'Choose a CSV file to import.';
export const WRONG_TYPE_MESSAGE = 'Choose a .csv file.';
export const EMPTY_FILE_MESSAGE = 'That file is empty. Choose another file.';
export const UNREADABLE_MESSAGE =
  'That file could not be read as a CSV file. Save it as UTF-8 CSV and try again.';
export const TOO_LARGE_MESSAGE = 'That file is larger than 1 MB. Split it into smaller files.';

/** Browsers report .csv as text/csv, application/vnd.ms-excel (Windows) or nothing at all. */
const CSV_TYPES: ReadonlySet<string> = new Set([
  '',
  'text/csv',
  'text/plain',
  'application/csv',
  'application/vnd.ms-excel',
]);

/** The message for a file that must not be sent, or null when its name, type and size are allowed. */
export function csvFileError(file: { name: string; type: string; size: number }): string | null {
  if (file.name === '') return NO_FILE_MESSAGE; // an empty file input submits a nameless empty File
  if (!file.name.toLowerCase().endsWith('.csv') || !CSV_TYPES.has(file.type)) {
    return WRONG_TYPE_MESSAGE;
  }
  if (file.size <= 0) return EMPTY_FILE_MESSAGE;
  if (file.size > MAX_IMPORT_BYTES) return TOO_LARGE_MESSAGE;
  return null;
}

/** A `File` from the action's FormData that passes `csvFileError`. */
export const csvFileSchema = z
  .custom<File>((value) => value instanceof File, NO_FILE_MESSAGE)
  .superRefine((file, context) => {
    const error = csvFileError(file);
    if (error) context.addIssue({ code: z.ZodIssueCode.custom, message: error });
  });

/** One problem from the backend: `row` is the spreadsheet row (header = 1), null for the whole file. */
export type ImportIssue = { row: number | null; column: string | null; message: string };

export type ImportOutcome = {
  imported: number;
  errors: ImportIssue[];
  truncated: boolean;
};

/** Where a problem is, in words: "Row 3", "Whole file". */
export function issueLocation(issue: ImportIssue): string {
  return issue.row === null ? 'Whole file' : `Row ${issue.row}`;
}

/** The sample offered for download: every column, one active and one draft product. */
export const SAMPLE_CSV =
  [
    IMPORT_COLUMNS.join(','),
    'Blue mug,blue-mug,Stoneware mug that holds 350 ml,active,MUG-BLUE,1499,1999,400,25',
    'Linen tea towel,,,draft,TOWEL-LINEN,899,,120,10',
  ].join('\n') + '\n';

export const SAMPLE_FILE_NAME = 'products-import-sample.csv';
