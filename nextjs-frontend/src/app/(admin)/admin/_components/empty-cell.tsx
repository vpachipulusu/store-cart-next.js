/** An empty table value: a dash for sighted users, "None" for screen readers. */
export function EmptyCell() {
  return (
    <>
      <span aria-hidden="true">—</span>
      <span className="sr-only">None</span>
    </>
  );
}
