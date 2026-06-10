import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getConfigEffective } from "../api/client";

const show = (v: unknown) =>
  v === undefined ? "—" : typeof v === "string" ? v : JSON.stringify(v);

/**
 * Effective-config diff between this instance and another. The effective
 * payload is a flat dot-path record, so the diff is a key-union walk showing
 * only keys whose resolved values differ.
 */
export function ConfigDiff({
  instanceId,
  instances,
}: {
  instanceId: string;
  instances: Array<{ id: string; name: string }>;
}) {
  const [otherId, setOtherId] = useState("");

  const mineQ = useQuery({
    queryKey: ["config-effective", instanceId],
    queryFn: () => getConfigEffective(instanceId),
    enabled: !!otherId,
    retry: false,
  });
  const otherQ = useQuery({
    queryKey: ["config-effective", otherId],
    queryFn: () => getConfigEffective(otherId),
    enabled: !!otherId,
    retry: false,
  });

  const others = instances.filter((i) => i.id !== instanceId);
  const mine = mineQ.data;
  const other = otherQ.data;

  const diffs =
    mine && other
      ? [...new Set([...Object.keys(mine), ...Object.keys(other)])]
          .sort()
          .filter(
            (k) =>
              JSON.stringify(mine[k]?.value) !== JSON.stringify(other[k]?.value),
          )
      : [];

  return (
    <div data-testid="config-diff" className="panel flex flex-col gap-3 p-5">
      <div className="flex items-center justify-between gap-3">
        <p className="eyebrow">Compare config with…</p>
        <label htmlFor="select-diff-instance" className="sr-only">
          Instance to compare
        </label>
        <select
          id="select-diff-instance"
          data-testid="select-diff-instance"
          value={otherId}
          onChange={(e) => setOtherId(e.target.value)}
          className="max-w-xs truncate rounded-lg border border-line bg-ink-700/50 px-3 py-1.5 text-sm text-fg focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/30"
        >
          <option value="">— pick an instance —</option>
          {others.map((i) => (
            <option key={i.id} value={i.id}>
              {i.name}
            </option>
          ))}
        </select>
      </div>

      {otherId && mine && other && (
        <>
          {diffs.length === 0 ? (
            <p className="text-sm text-fg-faint">
              Effective configs are identical.
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-fg-faint">
                  <th className="py-1 pr-3 font-medium">Key</th>
                  <th className="py-1 pr-3 font-medium">This instance</th>
                  <th className="py-1 font-medium">
                    {others.find((i) => i.id === otherId)?.name}
                  </th>
                </tr>
              </thead>
              <tbody>
                {diffs.map((k) => (
                  <tr key={k} className="border-t border-line/40 align-top">
                    <td className="py-1.5 pr-3 font-mono text-xs text-fg">{k}</td>
                    <td className="py-1.5 pr-3 font-mono text-xs text-accent">
                      {show(mine[k]?.value)}
                    </td>
                    <td className="py-1.5 font-mono text-xs text-warn">
                      {show(other[k]?.value)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  );
}
