import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminAudit from "@/components/AdminAudit.vue";
import AdminEvaluations from "@/components/AdminEvaluations.vue";
import AdminKeys from "@/components/AdminKeys.vue";
import AdminView from "@/views/AdminView.vue";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

type Handler = (init?: RequestInit, url?: URL) => Response;

/** Answers each request by its method and API path. */
function serve(routes: Record<string, Handler>) {
  const fetch = vi.fn((input: string, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const handler = routes[`${init?.method ?? "GET"} ${url.pathname.replace("/api/v1", "")}`];
    return Promise.resolve(handler ? handler(init, url) : Response.json({ signal: "not_mocked" }, { status: 500 }));
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

const KEY = {
  id: "k-1",
  name: "Support bot",
  prefix: "mrag_3fA9",
  scopes: ["read", "ask"],
  created_at: "2026-10-18T10:00:00Z",
  last_used_at: null,
  revoked_at: null,
};

describe("AdminKeys", () => {
  it("lists keys, marks the one in use and revoked ones", async () => {
    serve({ "GET /keys": () => Response.json([KEY, { ...KEY, id: "k-2", name: "Old", revoked_at: "2026-10-18T11:00:00Z" }]) });
    const wrapper = mount(AdminKeys, { props: { currentKeyId: "k-1" } });
    await flushPromises();

    const rows = wrapper.findAll("tbody tr");
    expect(rows[0]!.text()).toContain("Support bot");
    expect(rows[0]!.text()).toContain("This browser");
    expect(rows[0]!.findAll(".chip").map((chip) => chip.text())).toEqual(["read", "ask"]);
    expect(rows[1]!.text()).toContain("Revoked");
    expect(rows[1]!.find("button").exists()).toBe(false);
  });

  it("creates a key with the chosen scopes and shows its secret once", async () => {
    let created: unknown = null;
    serve({
      "GET /keys": () => Response.json(created ? [KEY] : []),
      "POST /keys": (init) => {
        created = JSON.parse(String(init!.body));
        return Response.json({ ...KEY, key: "mrag_3fA9secretsecret" }, { status: 201 });
      },
    });
    const wrapper = mount(AdminKeys, { props: { currentKeyId: null } });
    await flushPromises();

    await wrapper.find("input.input").setValue("Support bot");
    await wrapper.find('input[value="admin"]').setValue(true);
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    expect(created).toEqual({ name: "Support bot", scopes: ["read", "ask", "admin"] });
    expect(wrapper.emitted("changed")).toHaveLength(1);
    expect(wrapper.find('[data-testid="new-key"]').text()).toBe("mrag_3fA9secretsecret");
    await wrapper.findAll(".created button").at(-1)!.trigger("click");
    expect(wrapper.find('[data-testid="new-key"]').exists()).toBe(false);
  });

  it("revokes a key once confirmed", async () => {
    const fetch = serve({ "GET /keys": () => Response.json([KEY]), "DELETE /keys/k-1": () => new Response(null, { status: 204 }) });
    vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    const wrapper = mount(AdminKeys, { props: { currentKeyId: null } });
    await flushPromises();

    await wrapper.find('[aria-label="Revoke Support bot"]').trigger("click");
    expect(fetch.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(false);
    await wrapper.find('[aria-label="Revoke Support bot"]').trigger("click");
    await flushPromises();
    expect(fetch.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(true);
  });
});

function run(id: string, created_at: string, mrr: number, top_k = 5, answer_metrics: Record<string, number> | null = null) {
  return {
    id,
    dataset: "handbook",
    dataset_version: "v1",
    cases: 53,
    parameters: { embedding_model: "text-embedding-3-small", search_mode: "hybrid", reranker: null, top_k, chunk_size: 1000 },
    metrics: { hit_rate: 0.9, recall: 0.8, mrr },
    answer_metrics,
    version: "0.1.0",
    created_at,
  };
}

describe("AdminEvaluations", () => {
  it("shows the latest run's scores against the previous run of the same setup", async () => {
    serve({
      "GET /evaluations": () =>
        Response.json({
          total: 4,
          offset: 0,
          limit: 100,
          items: [
            run("r-4", "2026-10-18T12:00:00Z", 0.72, 5, { correct: 0.81, grounded: 0.9 }),
            run("r-3", "2026-10-17T12:00:00Z", 0.9, 3),
            run("r-2", "2026-10-16T12:00:00Z", 0.7),
            run("r-1", "2026-10-15T12:00:00Z", 0.6),
          ],
        }),
    });
    const wrapper = mount(AdminEvaluations);
    await flushPromises();

    const tiles = wrapper.findAll(".tile").map((tile) => tile.text());
    expect(tiles[2]).toBe("MRR72%+2 pts");
    expect(tiles[0]).toContain("No change");
    expect(tiles[3]).toBe("Correct answers81%First run of this setup");
    // The run with top 3 is another setup: the trend has the three runs with top 5.
    expect(wrapper.find(".trend figcaption").text()).toBe("MRR, 3 runs");
    expect(wrapper.findAll("tbody tr")).toHaveLength(4);
    expect(wrapper.find("tbody tr").text()).toContain("81%");
  });

  it("explains how to record runs when there are none", async () => {
    serve({ "GET /evaluations": () => Response.json({ total: 0, offset: 0, limit: 100, items: [] }) });
    const wrapper = mount(AdminEvaluations);
    await flushPromises();

    expect(wrapper.text()).toContain("ragolex eval evals/handbook/v1");
  });
});

describe("AdminAudit", () => {
  it("lists events with who did them, and filters by action", async () => {
    const fetch = serve({
      "GET /audit": (_init, url) =>
        Response.json({
          total: 1,
          offset: 0,
          limit: 20,
          items: [
            {
              id: 1,
              action: url!.searchParams.get("action") ? "api_key.revoked" : "api_key.created",
              target: "k-1",
              details: { name: "Support bot", scopes: ["read", "ask"] },
              actor: { key_id: "k-0", name: "ops laptop" },
              request_id: "r-1",
              created_at: "2026-10-18T10:00:00Z",
            },
          ],
        }),
    });
    const wrapper = mount(AdminAudit);
    await flushPromises();

    expect(wrapper.find(".event").text()).toContain("api_key.created");
    expect(wrapper.find(".event").text()).toContain("By ops laptop · name: Support bot · scopes: read, ask");

    await wrapper.find("#audit-action").setValue("api_key.revoked");
    await wrapper.find("form").trigger("submit");
    await flushPromises();
    expect(String(fetch.mock.calls.at(-1)![0])).toContain("action=api_key.revoked");
    expect(wrapper.find(".event").text()).toContain("api_key.revoked");
  });
});

describe("AdminView", () => {
  const usage = {
    tenant: "acme",
    period_start: "2026-10-01T00:00:00Z",
    requests_per_minute: 600,
    answers: { used: 25, limit: 100 },
    storage_bytes: { used: 2048, limit: null },
    input_tokens: 1000,
    output_tokens: 200,
    cost_usd: 0.42,
  };

  it("shows usage against the limits, and the admin sections to admin keys", async () => {
    serve({
      "GET /me": () => Response.json({ tenant: "acme", scopes: ["admin", "read"], key_id: "k-1", auth_enabled: true }),
      "GET /usage": () => Response.json(usage),
    });
    const wrapper = mount(AdminView, { global: { stubs: { AdminKeys: true, AdminEvaluations: true, AdminAudit: true } } });
    await flushPromises();

    const tiles = wrapper.findAll(".tile").map((tile) => tile.text());
    expect(tiles[0]).toBe("Answers this month25of 100");
    expect(tiles[1]).toContain("No limit");
    expect(tiles[3]).toContain("$0.42");
    expect(wrapper.find('[role="progressbar"]').attributes("aria-valuenow")).toBe("25");
    expect(wrapper.findComponent({ name: "AdminKeys" }).exists()).toBe(true);
  });

  it("says what a key without the admin scope cannot see", async () => {
    serve({
      "GET /me": () => Response.json({ tenant: "acme", scopes: ["read"], key_id: "k-2", auth_enabled: true }),
      "GET /usage": () => Response.json(usage),
    });
    const wrapper = mount(AdminView, { global: { stubs: { AdminKeys: true, AdminEvaluations: true, AdminAudit: true } } });
    await flushPromises();

    expect(wrapper.text()).toContain("need a key with the admin scope");
    expect(wrapper.findComponent({ name: "AdminKeys" }).exists()).toBe(false);
  });
});
