'use client';

import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Download, Upload } from 'lucide-react';
import { importProductsAction } from '@/app/actions/product-import-actions';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  CSV_ACCEPT,
  csvFileError,
  IMPORT_COLUMNS,
  IMPORT_FILE_HINT,
  issueLocation,
  MAX_IMPORT_ROWS,
  NO_FILE_MESSAGE,
  SAMPLE_CSV,
  SAMPLE_FILE_NAME,
  type ImportOutcome,
} from '@/lib/products/csv-import';
import { Field } from './field';

const REQUEST_FAILED = 'The request failed. Please try again.';

/** Starts a download of the sample CSV without a server round trip. */
function downloadSample(): void {
  const url = URL.createObjectURL(new Blob([SAMPLE_CSV], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = SAMPLE_FILE_NAME;
  document.body.append(link);
  link.click();
  link.remove();
  // Revoking at once can cancel the download in some browsers.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`;
}

/** Text of the one always-present status region: progress, then the success count. */
function statusText(busy: boolean, outcome: ImportOutcome | null): string {
  if (busy) return 'Importing… keep this dialog open until it finishes.';
  if (outcome && outcome.errors.length === 0) {
    return `Imported ${plural(outcome.imported, 'product')}.`;
  }
  return '';
}

/**
 * "Import CSV" on the products page (KAN-74). The file is checked here (name, type, size), then sent with the
 * store id this page was rendered for; the action refuses it if the selected store changed. All rows are imported
 * or none: when any row fails, every problem is listed by row and column and nothing was saved.
 */
export function ProductImportDialog({
  storeId,
  storeName,
}: {
  storeId: string;
  storeName: string;
}) {
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<ImportOutcome | null>(null);
  const [busy, setBusy] = useState(false);
  const [inputKey, setInputKey] = useState(0);
  const mounted = useRef(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const wasBusy = useRef(false);
  const refocus = useRef<'file' | 'button'>('button');

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // A disabled control drops keyboard focus, so put it back when the import ends.
  useEffect(() => {
    if (busy) {
      wasBusy.current = true;
      return;
    }
    if (!wasBusy.current) return;
    wasBusy.current = false;
    (refocus.current === 'file' ? fileRef : buttonRef).current?.focus();
  }, [busy]);

  function clearFile() {
    setFile(null);
    setFileError(null);
    setInputKey((key) => key + 1);
  }

  function reset() {
    clearFile();
    setError(null);
    setOutcome(null);
  }

  function changeOpen(next: boolean) {
    if (busy) return; // keep the dialog while the upload runs
    setOpen(next);
    if (!next) reset();
  }

  function chooseFile(chosen: File | null) {
    setError(null);
    setOutcome(null);
    setFile(chosen);
    setFileError(chosen ? csvFileError(chosen) : null);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setError(null);
    setOutcome(null);
    if (!file) {
      setFileError(NO_FILE_MESSAGE);
      return;
    }
    const invalid = csvFileError(file);
    if (invalid) {
      setFileError(invalid);
      return;
    }
    const form = new FormData();
    form.append('file', file);
    setBusy(true);
    refocus.current = 'button';
    try {
      const response = await importProductsAction(storeId, form);
      if (!mounted.current) return;
      if (!response.success) {
        setError(response.error);
      } else {
        setOutcome(response.data);
        if (response.data.imported > 0) {
          clearFile(); // the same file would only fail as duplicates now
          refocus.current = 'file';
        }
      }
    } catch {
      if (mounted.current) setError(REQUEST_FAILED);
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      <DialogTrigger asChild>
        <Button variant="outline">
          <Upload aria-hidden="true" />
          Import CSV
        </Button>
      </DialogTrigger>
      <DialogContent
        className="max-h-[90vh] max-w-2xl overflow-y-auto"
        onEscapeKeyDown={(event) => busy && event.preventDefault()}
        onInteractOutside={(event) => busy && event.preventDefault()}
      >
        <DialogHeader>
          <DialogTitle>Import products</DialogTitle>
          <DialogDescription>
            {`Add products to ${storeName} from a CSV file: one product per row, up to ${MAX_IMPORT_ROWS} rows. Prices are in minor units (1499 is 14.99). If any row has a problem, nothing is imported.`}
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Button type="button" variant="link" className="h-auto px-0" onClick={downloadSample}>
            <Download aria-hidden="true" />
            Download sample CSV
          </Button>
          <span className="text-muted-foreground">Columns: {IMPORT_COLUMNS.join(', ')}</span>
        </div>

        <form onSubmit={submit} className="space-y-4">
          <Field
            id="product-import-file"
            label="CSV file"
            hint={IMPORT_FILE_HINT}
            error={fileError ?? undefined}
          >
            {(describedBy) => (
              <Input
                key={inputKey}
                ref={fileRef}
                id="product-import-file"
                type="file"
                accept={CSV_ACCEPT}
                disabled={busy}
                aria-invalid={fileError ? true : undefined}
                aria-describedby={describedBy}
                onChange={(event) => chooseFile(event.target.files?.[0] ?? null)}
              />
            )}
          </Field>
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <p role="status" className="text-sm text-muted-foreground" data-testid="import-status">
            {statusText(busy, outcome)}
          </p>
          {outcome && !busy && <ImportResult outcome={outcome} />}
          <Button ref={buttonRef} type="submit" disabled={busy || !file || fileError !== null}>
            {busy ? 'Importing…' : 'Import'}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ImportResult({ outcome }: { outcome: ImportOutcome }) {
  if (outcome.errors.length === 0) return null; // the success text is in the status region
  return (
    <div className="space-y-2" data-testid="import-errors">
      <p role="alert" className="text-sm font-medium text-destructive">
        {`Nothing was imported. Fix ${plural(outcome.errors.length, 'problem')} and try again.`}
      </p>
      <Table stacked>
        <TableCaption>Problems in the file</TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead>Location</TableHead>
            <TableHead>Column</TableHead>
            <TableHead>Problem</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {outcome.errors.map((issue, index) => (
            <TableRow key={`${issue.row ?? 'file'}-${issue.column ?? ''}-${index}`}>
              <TableCell label="Location">{issueLocation(issue)}</TableCell>
              <TableCell label="Column">{issue.column ?? '—'}</TableCell>
              <TableCell label="Problem">{issue.message}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {outcome.truncated && (
        <p className="text-sm text-muted-foreground">
          Only the first problems are listed. Fix these and import again to see the rest.
        </p>
      )}
    </div>
  );
}
