import { describe, it, expect, vi, afterEach } from "vitest";
import {
  listInstances,
  getSchema,
  getConfig,
  patchConfig,
  startInstance,
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

describe("api client", () => {
  it("parses instances", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse([
          {
            id: "a",
            name: "foo",
            status: "running",
            base_url: "http://x",
            project_root: "/p/foo",
            state_dir: "/p/foo/.brainpalace",
            pid: 1,
            mode: "project",
            started_at: "",
          },
        ]),
      ),
    );
    const rows = await listInstances();
    expect(rows[0].id).toBe("a");
    expect(rows[0].status).toBe("running");
  });

  it("parses the UI schema", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({
          sections: [
            {
              key: "embedding",
              label: "Embedding",
              fields: [
                {
                  key: "provider",
                  dotpath: "embedding.provider",
                  label: "Provider",
                  widget: "enum",
                  options: ["openai", "ollama"],
                },
              ],
            },
          ],
        }),
      ),
    );
    const schema = await getSchema();
    expect(schema.sections[0].key).toBe("embedding");
    expect(schema.sections[0].fields[0].widget).toBe("enum");
  });

  it("returns config as a nested record", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({ embedding: { provider: "openai", api_key: "********" } }),
      ),
    );
    const cfg = await getConfig("a");
    expect((cfg.embedding as Record<string, unknown>).provider).toBe("openai");
  });

  it("PATCHes config with values + restart flag", async () => {
    const fetchMock = vi.fn(
      async (_url: string, _init?: RequestInit) =>
        jsonResponse({ ok: true, restarted: false }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const res = await patchConfig("a", { embedding: { provider: "ollama" } }, false);
    expect(res.ok).toBe(true);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/dashboard/api/instances/a/config");
    expect(init?.method).toBe("PATCH");
    expect(JSON.parse(init?.body as string)).toEqual({
      values: { embedding: { provider: "ollama" } },
      unset: [],
      restart: false,
      force_reindex: false,
    });
  });

  it("throws the 422 error payload on validation failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({ errors: [{ field: "embedding.provider", message: "bad" }] }, 422),
      ),
    );
    await expect(
      patchConfig("a", { embedding: { provider: "nope" } }, false),
    ).rejects.toMatchObject({ errors: [{ field: "embedding.provider", message: "bad" }] });
  });

  it("starts an instance via POST", async () => {
    const fetchMock = vi.fn(
      async (_url: string, _init?: RequestInit) => jsonResponse({ ok: true }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await startInstance("a");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/dashboard/api/instances/a/start");
    expect(init?.method).toBe("POST");
  });
});
