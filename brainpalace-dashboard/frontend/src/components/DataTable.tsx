import { useMemo, useState, type ReactNode } from "react";
import { ChevronUp, ChevronDown, ChevronsUpDown } from "lucide-react";

export type Column<T> = {
  key: string;
  header: string;
  /** Cell renderer. */
  cell: (row: T) => ReactNode;
  /** Value used for sorting; omit to make the column non-sortable. */
  sortValue?: (row: T) => string | number;
  align?: "left" | "right" | "center";
  className?: string;
};

export function DataTable<T>({
  rows,
  columns,
  rowKey,
  rowTestId,
  leading,
  trailing,
  empty,
  onRowClick,
}: {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string;
  rowTestId?: (row: T) => string;
  /** Optional leading cell (e.g. a bulk-select checkbox) per row + header. */
  leading?: { header: ReactNode; cell: (row: T) => ReactNode };
  /** Optional trailing actions cell. */
  trailing?: { header: ReactNode; cell: (row: T) => ReactNode };
  empty?: ReactNode;
  /** Optional whole-row click handler (makes rows behave like buttons). */
  onRowClick?: (row: T) => void;
}) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [dir, setDir] = useState<"asc" | "desc">("asc");

  const sorted = useMemo(() => {
    if (!sortKey) return rows;
    const col = columns.find((c) => c.key === sortKey);
    if (!col?.sortValue) return rows;
    const out = [...rows].sort((a, b) => {
      const av = col.sortValue!(a);
      const bv = col.sortValue!(b);
      if (av < bv) return dir === "asc" ? -1 : 1;
      if (av > bv) return dir === "asc" ? 1 : -1;
      return 0;
    });
    return out;
  }, [rows, columns, sortKey, dir]);

  const toggleSort = (key: string) => {
    if (sortKey === key) setDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setDir("asc");
    }
  };

  const alignClass = (a?: Column<T>["align"]) =>
    a === "right" ? "text-right" : a === "center" ? "text-center" : "text-left";

  return (
    <div className="panel overflow-hidden">
      <table className="w-full border-collapse text-sm" data-testid="data-table">
        <thead>
          <tr className="border-b border-line">
            {leading && (
              <th scope="col" className="w-10 px-4 py-3">
                {leading.header}
              </th>
            )}
            {columns.map((col) => {
              const active = sortKey === col.key;
              const Sort = !active
                ? ChevronsUpDown
                : dir === "asc"
                  ? ChevronUp
                  : ChevronDown;
              return (
                <th
                  key={col.key}
                  scope="col"
                  className={`px-4 py-3 font-mono text-[0.66rem] font-semibold uppercase tracking-[0.16em] text-fg-faint ${alignClass(col.align)}`}
                >
                  {col.sortValue ? (
                    <button
                      type="button"
                      onClick={() => toggleSort(col.key)}
                      className="inline-flex items-center gap-1.5 transition-colors hover:text-fg-muted focus:outline-none focus-visible:text-fg"
                    >
                      {col.header}
                      <Sort
                        className={`h-3 w-3 ${active ? "text-accent" : "opacity-50"}`}
                        aria-hidden="true"
                      />
                    </button>
                  ) : (
                    col.header
                  )}
                </th>
              );
            })}
            {trailing && (
              <th scope="col" className="px-4 py-3 text-right">
                {trailing.header}
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {sorted.length === 0 ? (
            <tr>
              <td
                colSpan={
                  columns.length + (leading ? 1 : 0) + (trailing ? 1 : 0)
                }
                className="px-4 py-12 text-center text-sm text-fg-muted"
              >
                {empty ?? "Nothing here yet."}
              </td>
            </tr>
          ) : (
            sorted.map((row) => (
              <tr
                key={rowKey(row)}
                data-testid={rowTestId?.(row)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={`border-b border-line/50 transition-colors last:border-0 hover:bg-ink-700/30 ${onRowClick ? "cursor-pointer" : ""}`}
              >
                {leading && <td className="px-4 py-3">{leading.cell(row)}</td>}
                {columns.map((col) => (
                  <td
                    key={col.key}
                    className={`px-4 py-3 ${alignClass(col.align)} ${col.className ?? ""}`}
                  >
                    {col.cell(row)}
                  </td>
                ))}
                {trailing && (
                  <td className="px-4 py-3 text-right">{trailing.cell(row)}</td>
                )}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
