import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Documents } from "./Documents";
import { ToastProvider } from "../components/Toast";
import * as client from "../api/client";

vi.mock("../api/client");

const folders = {
  total: 1,
  folders: [
    {
      folder_path: "/proj",
      chunk_count: 3,
      last_indexed: null,
      watch_mode: "off",
      watch_debounce_seconds: null,
    },
  ],
};

const docs = {
  folder: "/proj",
  total: 2,
  files: [
    { path: "/proj/a.py", chunk_count: 2, size_bytes: 10, mtime: 1, last_embedded_at: 1 },
    { path: "/proj/b.md", chunk_count: 1, size_bytes: 20, mtime: 2, last_embedded_at: 2 },
  ],
};

const chunks = {
  path: "/proj/a.py",
  total_chunks: 2,
  chunks: [
    { chunk_id: "c1", text: "def a(): ...", metadata: { language: "python" } },
    { chunk_id: "c2", text: "def b(): ...", metadata: { language: "python" } },
  ],
};

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <Documents instanceId="i1" />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("Documents tab", () => {
  beforeEach(() => {
    vi.mocked(client.getFolders).mockResolvedValue(folders);
    vi.mocked(client.getDocuments).mockResolvedValue(docs);
    vi.mocked(client.getDocumentChunks).mockResolvedValue(chunks);
  });

  it("lists files of the selected folder with chunk counts", async () => {
    mount();
    expect(await screen.findByText("/proj/a.py")).toBeInTheDocument();
    expect(screen.getByText("/proj/b.md")).toBeInTheDocument();
    await waitFor(() =>
      expect(client.getDocuments).toHaveBeenCalledWith(
        "i1",
        expect.objectContaining({ folder: "/proj" }),
      ),
    );
  });

  it("opens the chunk drawer on row click", async () => {
    mount();
    fireEvent.click(await screen.findByText("/proj/a.py"));
    expect(await screen.findByTestId("chunk-drawer")).toBeInTheDocument();
    expect(await screen.findByTestId("chunk-c1")).toBeInTheDocument();
  });

  it("requests 100 files per page and pages via offset", async () => {
    // 250 files across 3 pages; the tab must fetch a page of 100 at a time.
    vi.mocked(client.getDocuments).mockResolvedValue({
      folder: "/proj",
      total: 250,
      files: docs.files,
    });
    mount();
    await screen.findByText("/proj/a.py");
    await waitFor(() =>
      expect(client.getDocuments).toHaveBeenCalledWith(
        "i1",
        expect.objectContaining({ folder: "/proj", limit: 100, offset: 0 }),
      ),
    );
    expect(screen.getByTestId("doc-pager")).toHaveTextContent("Page 1 of 3");

    fireEvent.click(screen.getByTestId("doc-next"));
    await waitFor(() =>
      expect(client.getDocuments).toHaveBeenCalledWith(
        "i1",
        expect.objectContaining({ folder: "/proj", limit: 100, offset: 100 }),
      ),
    );
  });

  it("resets to the first page when the filter changes", async () => {
    vi.mocked(client.getDocuments).mockResolvedValue({
      folder: "/proj",
      total: 250,
      files: docs.files,
    });
    mount();
    await screen.findByText("/proj/a.py");
    fireEvent.click(screen.getByTestId("doc-next")); // page 2 (offset 100)
    await waitFor(() =>
      expect(client.getDocuments).toHaveBeenLastCalledWith(
        "i1",
        expect.objectContaining({ offset: 100 }),
      ),
    );
    fireEvent.change(screen.getByTestId("input-doc-contains"), {
      target: { value: "a.py" },
    });
    await waitFor(() =>
      expect(client.getDocuments).toHaveBeenLastCalledWith(
        "i1",
        expect.objectContaining({ contains: "a.py", offset: 0 }),
      ),
    );
  });
});
