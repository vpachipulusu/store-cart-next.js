import * as React from "react"
import { ChevronLeft, ChevronRight } from "lucide-react"

import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"

interface PageRange {
  page: number
  from: number
  to: number
  pageCount: number
}

/** Clamp `page` into range and compute the "Showing from to to of total" bounds. */
export function getRange(page: number, pageSize: number, total: number): PageRange {
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  const current = Math.min(Math.max(1, page), pageCount)
  if (total <= 0) return { page: current, from: 0, to: 0, pageCount }
  return {
    page: current,
    from: (current - 1) * pageSize + 1,
    to: Math.min(current * pageSize, total),
    pageCount,
  }
}

interface PaginationProps extends React.HTMLAttributes<HTMLElement> {
  page: number
  pageSize: number
  total: number
  onPageChange: (page: number) => void
}

function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
  className,
  ...props
}: PaginationProps) {
  const range = getRange(page, pageSize, total)

  return (
    <nav
      aria-label="Pagination"
      className={cn(
        "flex flex-wrap items-center justify-between gap-3 py-3 text-sm",
        className
      )}
      {...props}
    >
      <p aria-live="polite" className="tabular-nums text-muted-foreground">
        {`Showing ${range.from} to ${range.to} of ${total}`}
      </p>
      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="icon"
          aria-label="Previous page"
          disabled={range.page <= 1}
          onClick={() => onPageChange(range.page - 1)}
        >
          <ChevronLeft aria-hidden="true" />
        </Button>
        <span aria-current="page" className="min-w-24 text-center tabular-nums">
          {`Page ${range.page} of ${range.pageCount}`}
        </span>
        <Button
          type="button"
          variant="outline"
          size="icon"
          aria-label="Next page"
          disabled={range.page >= range.pageCount}
          onClick={() => onPageChange(range.page + 1)}
        >
          <ChevronRight aria-hidden="true" />
        </Button>
      </div>
    </nav>
  )
}

export { Pagination }
