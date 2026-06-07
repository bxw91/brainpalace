import { describe, it, expect, vi, afterEach } from "vitest";
import {
  getFolders,
  getJobs,
  getCache,
  getMemories,
  getQueries,
  getQueryDetail,
  replayQuery,
  getLogs,
  clearCache,
  resetIndex,
  addFolder,
  removeFolder,
  cancelJob,
  gitReindex,
  sessionsReindex,
  memoryObsolete,
  memoryDelete,
  memoryRebuild,
  InstanceUnreachableError,
} from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function stub(body: unknown, status = 200) {
  const fetchMock = vi.fn(
    async (_url: string, _init?: RequestInit) => jsonResponse(body, status),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("data api client", () => {
  it("getFolders builds the right URL and parses", async () => {
    const f = stub({ folders: [{ folder_path: "/p", chunk_count: 3 }], total: 1 });
    const res = await getFolders("a");
    expect(f.mock.calls[0][0]).toBe("/dashboard/api/instances/a/folders");
    expect(res.total).toBe(1);
    expect(res.folders[0].folder_path).toBe("/p");
  });

  it("getJobs parses jobs array", async () => {
    const f = stub({ jobs: [{ id: "job_1", status: "done" }] });
    const res = await getJobs("a");
    expect(f.mock.calls[0][0]).toBe("/dashboard/api/instances/a/jobs");
    expect(res.jobs[0].id).toBe("job_1");
  });

  it("getCache parses hit_rate", async () => {
    const f = stub({ hits: 41, misses: 9, hit_rate: 0.82, entry_count: 10, mem_entries: 5, size_bytes: 100 });
    const res = await getCache("a");
    expect(f.mock.calls[0][0]).toBe("/dashboard/api/instances/a/cache");
    expect(res.hit_rate).toBe(0.82);
  });

  it("getMemories parses memories list", async () => {
    const f = stub({ memories: [], total: 0, char_count: 0, char_cap: 8000 });
    const res = await getMemories("a");
    expect(f.mock.calls[0][0]).toBe("/dashboard/api/instances/a/memories");
    expect(res.char_cap).toBe(8000);
  });

  it("getQueries builds query string with mode + since", async () => {
    const f = stub([{ id: "q1", ts: 1, mode: "hybrid", query: "x", top_k: 5, latency_ms: 10, result_count: 2, alpha: 0.5 }]);
    const rows = await getQueries("a", { mode: "hybrid", since: 100, limit: 50 });
    const url = f.mock.calls[0][0] as string;
    expect(url.startsWith("/dashboard/api/instances/a/queries?")).toBe(true);
    expect(url).toContain("mode=hybrid");
    expect(url).toContain("since=100");
    expect(url).toContain("limit=50");
    expect(rows[0].id).toBe("q1");
  });

  it("getQueryDetail builds detail URL", async () => {
    const f = stub({ id: "q1", ts: 1, mode: "hybrid", query: "x", top_k: 5, latency_ms: 10, result_count: 1, alpha: null, filters: {}, results: [] });
    const d = await getQueryDetail("a", "q1");
    expect(f.mock.calls[0][0]).toBe("/dashboard/api/instances/a/queries/q1");
    expect(d.id).toBe("q1");
  });

  it("replayQuery POSTs query/mode/top_k", async () => {
    const f = stub({ results: [], query_time_ms: 5, total_results: 0 });
    await replayQuery("a", { query: "hello", mode: "vector", top_k: 8 });
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/dashboard/api/instances/a/queries/replay");
    expect((init as RequestInit).method).toBe("POST");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      query: "hello",
      mode: "vector",
      top_k: 8,
    });
  });

  it("getLogs builds URL with lines + level", async () => {
    const f = stub({ lines: ["a", "b"] });
    const res = await getLogs("a", 50, "ERROR");
    const url = f.mock.calls[0][0] as string;
    expect(url.startsWith("/dashboard/api/instances/a/logs?")).toBe(true);
    expect(url).toContain("lines=50");
    expect(url).toContain("level=ERROR");
    expect(res.lines).toEqual(["a", "b"]);
  });

  it("action calls hit the right method+URL", async () => {
    const f = stub({ ok: true });
    await clearCache("a");
    await resetIndex("a");
    await addFolder("a", { path: "/p", include_type: "code" });
    await removeFolder("a", "/p");
    await cancelJob("a", "job_1");
    await gitReindex("a");
    await sessionsReindex("a");
    await memoryObsolete("a", "m1");
    await memoryDelete("a", "m1");
    await memoryRebuild("a");
    const seen = f.mock.calls.map((c) => [
      (c[1] as RequestInit | undefined)?.method ?? "GET",
      c[0],
    ]);
    expect(seen).toContainEqual(["DELETE", "/dashboard/api/instances/a/cache"]);
    expect(seen).toContainEqual(["DELETE", "/dashboard/api/instances/a/index"]);
    expect(seen).toContainEqual(["POST", "/dashboard/api/instances/a/index"]);
    expect(seen).toContainEqual(["DELETE", "/dashboard/api/instances/a/folders"]);
    expect(seen).toContainEqual(["DELETE", "/dashboard/api/instances/a/jobs/job_1"]);
    expect(seen).toContainEqual(["POST", "/dashboard/api/instances/a/git/reindex"]);
    expect(seen).toContainEqual(["POST", "/dashboard/api/instances/a/sessions/reindex"]);
    expect(seen).toContainEqual(["POST", "/dashboard/api/instances/a/memories/m1/obsolete"]);
    expect(seen).toContainEqual(["DELETE", "/dashboard/api/instances/a/memories/m1"]);
    expect(seen).toContainEqual(["POST", "/dashboard/api/instances/a/memories/rebuild"]);
  });

  it("data reads throw InstanceUnreachableError on a 502", async () => {
    stub({ detail: "instance not running", upstream_status: 502 }, 502);
    await expect(getFolders("a")).rejects.toBeInstanceOf(InstanceUnreachableError);
  });
});
