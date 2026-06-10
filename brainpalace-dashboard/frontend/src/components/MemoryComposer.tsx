import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Loader2 } from "lucide-react";
import { memoryCreate } from "../api/client";
import { useToast } from "./Toast";

/** Create a curated memory (the write half of remember/recall). */
export function MemoryComposer({ instanceId }: { instanceId: string }) {
  const [text, setText] = useState("");
  const [section, setSection] = useState("");
  const { toast } = useToast();
  const qc = useQueryClient();

  const createM = useMutation({
    mutationFn: () =>
      memoryCreate(instanceId, {
        text: text.trim(),
        ...(section.trim() ? { section: section.trim() } : {}),
      }),
    onSuccess: () => {
      setText("");
      toast("Memory saved.", "success");
      qc.invalidateQueries({ queryKey: ["memories", instanceId] });
      qc.invalidateQueries({ queryKey: ["status", instanceId] });
    },
    onError: (e: unknown) =>
      toast(e instanceof Error ? e.message : "Failed to save memory.", "error"),
  });

  return (
    <div data-testid="memory-composer" className="flex flex-wrap items-end gap-3">
      <div className="min-w-0 flex-1">
        <label
          htmlFor="input-memory-text"
          className="mb-1.5 block text-xs font-medium text-fg-muted"
        >
          New memory
        </label>
        <input
          id="input-memory-text"
          data-testid="input-memory-text"
          type="text"
          value={text}
          placeholder="Something worth remembering…"
          onChange={(e) => setText(e.target.value)}
          className="w-full rounded-lg border border-line bg-ink-900/50 px-3 py-2 text-sm text-fg outline-none transition-colors placeholder:text-fg-faint focus:border-accent/50 focus:ring-2 focus:ring-accent/30"
        />
      </div>
      <div>
        <label
          htmlFor="input-memory-section"
          className="mb-1.5 block text-xs font-medium text-fg-muted"
        >
          Section (optional)
        </label>
        <input
          id="input-memory-section"
          data-testid="input-memory-section"
          type="text"
          value={section}
          onChange={(e) => setSection(e.target.value)}
          className="w-40 rounded-lg border border-line bg-ink-900/50 px-3 py-2 text-sm text-fg focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/30"
        />
      </div>
      <button
        type="button"
        data-testid="btn-memory-save"
        disabled={!text.trim() || createM.isPending}
        onClick={() => createM.mutate()}
        className="btn-primary btn-sm"
      >
        {createM.isPending ? (
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        ) : (
          <Plus className="h-4 w-4" aria-hidden="true" />
        )}
        Save
      </button>
    </div>
  );
}
