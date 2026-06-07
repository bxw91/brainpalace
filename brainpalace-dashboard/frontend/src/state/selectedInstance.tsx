import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { Instance } from "../api/types";

type SelectedInstanceCtx = {
  selectedId: string | null;
  setSelectedId: (id: string | null) => void;
  selected: Instance | null;
  instances: Instance[];
};

const Ctx = createContext<SelectedInstanceCtx | null>(null);

const STORAGE_KEY = "bp.dashboard.selectedInstance";

export function SelectedInstanceProvider({
  instances,
  children,
}: {
  instances: Instance[];
  children: ReactNode;
}) {
  const [selectedId, setSelectedIdRaw] = useState<string | null>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch {
      return null;
    }
  });

  const setSelectedId = (id: string | null) => {
    setSelectedIdRaw(id);
    try {
      if (id) localStorage.setItem(STORAGE_KEY, id);
      else localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore storage failures */
    }
  };

  // Auto-select the first instance once data arrives, or recover if the
  // selected instance disappears from the fleet.
  useEffect(() => {
    if (instances.length === 0) return;
    if (!selectedId || !instances.some((i) => i.id === selectedId)) {
      setSelectedId(instances[0].id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [instances]);

  const selected = useMemo(
    () => instances.find((i) => i.id === selectedId) ?? null,
    [instances, selectedId],
  );

  const value = useMemo(
    () => ({ selectedId, setSelectedId, selected, instances }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [selectedId, selected, instances],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSelectedInstance(): SelectedInstanceCtx {
  const ctx = useContext(Ctx);
  if (!ctx)
    throw new Error(
      "useSelectedInstance must be used within SelectedInstanceProvider",
    );
  return ctx;
}

/** Non-throwing reader — returns null outside a provider (used by tab tests). */
export function useOptionalSelectedInstance(): SelectedInstanceCtx | null {
  return useContext(Ctx);
}
