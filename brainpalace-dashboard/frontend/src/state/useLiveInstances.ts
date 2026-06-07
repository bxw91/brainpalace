import { useEffect, useState } from "react";
import type { QueryClient } from "@tanstack/react-query";
import { Instance } from "../api/types";

/**
 * Subscribe to the dashboard's SSE stream and push each `instances` payload
 * straight into the TanStack Query cache under `["instances"]`, so every tab
 * sees fresh fleet state from a single connection.
 *
 * If the stream errors (no SSE support, server hiccup), `fallback` flips true;
 * callers can then keep their existing `refetchInterval` polling alive. We tear
 * the stream down on unmount.
 */
export function useLiveInstances(qc: QueryClient): { fallback: boolean } {
  const [fallback, setFallback] = useState(false);

  useEffect(() => {
    if (typeof EventSource === "undefined") {
      setFallback(true);
      return;
    }

    let es: EventSource;
    try {
      es = new EventSource("/dashboard/api/events");
    } catch {
      setFallback(true);
      return;
    }

    const onInstances = (e: MessageEvent) => {
      setFallback(false);
      try {
        const parsed = Instance.array().parse(JSON.parse(e.data));
        qc.setQueryData(["instances"], parsed);
      } catch {
        /* ignore malformed frames; polling/next frame recovers */
      }
    };

    es.addEventListener("instances", onInstances as EventListener);
    es.onerror = () => setFallback(true);

    return () => {
      es.removeEventListener("instances", onInstances as EventListener);
      es.close();
    };
  }, [qc]);

  return { fallback };
}
