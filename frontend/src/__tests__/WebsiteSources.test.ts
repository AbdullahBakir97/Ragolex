import { flushPromises, mount, RouterLinkStub } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import WebsiteSources from "@/components/WebsiteSources.vue";

const SOURCE = {
  id: "s-1",
  kind: "website",
  url: "https://docs.example.com/guide/",
  max_pages: 50,
  sync_interval_hours: 24,
  pages_count: 3,
  syncing: false,
  last_synced_at: "2026-10-18T10:00:00Z",
  next_sync_at: "2999-01-01T00:00:00Z",
  last_error: null,
  tags: ["docs"],
  created_at: "2026-10-18T09:00:00Z",
};

afterEach(() => vi.unstubAllGlobals());

/** Answers the requests in turn with `bodies`; the workspace's connections are `connections`. */
function respond(...bodies: unknown[]) {
  return respondWith([], ...bodies);
}

function respondWith(connections: unknown[], ...bodies: unknown[]) {
  const queue = [...bodies];
  const fetch = vi.fn((url: string) => {
    if (url === "/api/v1/connections") {
      return Promise.resolve(Response.json({ items: connections, available: ["notion"], redirect_uri: "x" }));
    }
    const body = queue.shift();
    return Promise.resolve(body === null ? new Response(null, { status: 204 }) : Response.json(body));
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

/** The requests made, other than for the connections. */
function calls(fetch: ReturnType<typeof respond>) {
  return fetch.mock.calls.filter(([url]) => url !== "/api/v1/connections") as unknown as [string, RequestInit][];
}

describe("WebsiteSources", () => {
  it("lists websites with their pages, schedule and last sync", async () => {
    respond({ items: [{ ...SOURCE, last_error: "docs.example.com could not be resolved" }] });

    const wrapper = mount(WebsiteSources, { props: { project: "demo" } });
    await flushPromises();

    expect(wrapper.find(".url").text()).toBe(SOURCE.url);
    expect(wrapper.text()).toContain("3 of at most 50 pages · Every day · Synced");
    expect(wrapper.find(".error").text()).toContain("docs.example.com could not be resolved. Its pages are kept.");
    expect(wrapper.find(".tags").text()).toBe("docs");
  });

  it("adds a website with its limits, schedule and tags", async () => {
    const fetch = respond({ items: [] }, SOURCE, { items: [SOURCE] });
    const wrapper = mount(WebsiteSources, { props: { project: "demo" } });
    await flushPromises();

    await wrapper.find("input[type=url]").setValue("https://docs.example.com/guide/");
    await wrapper.find("input[type=number]").setValue(20);
    await wrapper.findAll("select")[1]!.setValue(0);
    await wrapper.find('input[aria-label="Tags for its pages"]').setValue("Guides, v2");
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    const [url, init] = calls(fetch)[1]!;
    expect(url).toBe("/api/v1/projects/demo/sources");
    expect(JSON.parse(String(init.body))).toEqual({
      kind: "website",
      url: "https://docs.example.com/guide/",
      max_pages: 20,
      sync_interval_hours: 0,
      tags: ["guides", "v2"],
    });
    expect(wrapper.emitted("synced")).toHaveLength(1);
    expect(wrapper.findAll(".item")).toHaveLength(1);
  });

  it("adds a GitHub repository, checking its address", async () => {
    const fetch = respond({ items: [] }, { ...SOURCE, kind: "github" }, { items: [] });
    const wrapper = mount(WebsiteSources, { props: { project: "demo" } });
    await flushPromises();

    await wrapper.findAll("select")[0]!.setValue("github");
    expect(wrapper.find("input[type=url]").attributes("placeholder")).toContain("github.com/owner/repo");
    await wrapper.find("input[type=url]").setValue("https://github.com/acme");
    expect(wrapper.find("button[type=submit]").attributes("disabled")).toBeDefined();
    await wrapper.find("input[type=url]").setValue("https://github.com/acme/handbook/tree/main/docs");
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    expect(JSON.parse(String(calls(fetch)[1]![1].body))).toMatchObject({
      kind: "github",
      url: "https://github.com/acme/handbook/tree/main/docs",
    });
  });

  it("removes a website, keeping its pages when asked", async () => {
    const fetch = respond({ items: [SOURCE] }, null, { items: [] });
    const wrapper = mount(WebsiteSources, { props: { project: "demo" } });
    await flushPromises();

    await wrapper.find('button[aria-label="Remove https://docs.example.com/guide/"]').trigger("click");
    await wrapper.find(".keep input").setValue(true);
    await wrapper.find(".confirm .btn-danger").trigger("click");
    await flushPromises();

    const [url, init] = calls(fetch)[1]!;
    expect(url).toBe("/api/v1/projects/demo/sources/s-1?keep_files=true");
    expect(init.method).toBe("DELETE");
    expect(wrapper.text()).toContain("No sources yet.");
  });

  it("adds Notion pages through one of the workspace's connections", async () => {
    const notion = { id: "con_aaaaaaaaaaaaaaaaaaaaaa", kind: "notion", account: "Acme wiki", sources_count: 0 };
    const drive = { id: "con_bbbbbbbbbbbbbbbbbbbbbb", kind: "google_drive", account: "ada@example.com" };
    const added = { ...SOURCE, kind: "notion", url: "https://www.notion.so/", connection_id: notion.id };
    const fetch = respondWith([notion, drive], { items: [] }, added, { items: [added] });
    const wrapper = mount(WebsiteSources, { props: { project: "demo" }, global: { stubs: { RouterLink: RouterLinkStub } } });
    await flushPromises();

    await wrapper.findAll("select")[0]!.setValue("notion");
    const connection = wrapper.findAll("select")[1]!;
    expect(connection.findAll("option").map((o) => o.text())).toEqual(["Acme wiki"]);
    // The address is optional: empty, every page the connection can read.
    expect(wrapper.find("input[type=url]").attributes("required")).toBeUndefined();
    await wrapper.find("input[type=url]").setValue("https://example.com/page");
    expect(wrapper.find("button[type=submit]").attributes("disabled")).toBeDefined();
    await wrapper.find("input[type=url]").setValue("");
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    expect(JSON.parse(String(calls(fetch)[1]![1].body))).toEqual({
      kind: "notion",
      connection_id: notion.id,
      max_pages: 50,
      sync_interval_hours: 24,
      tags: [],
    });
    expect(wrapper.find(".item").text()).toContain("Through Acme wiki");
  });

  it("says where to connect Google Drive when the workspace has no connection", async () => {
    respond({ items: [] });
    const wrapper = mount(WebsiteSources, { props: { project: "demo" }, global: { stubs: { RouterLink: RouterLinkStub } } });
    await flushPromises();

    await wrapper.findAll("select")[0]!.setValue("google_drive");
    expect(wrapper.find(".no-connection").text()).toContain("no Google Drive connection yet");
    expect(wrapper.findComponent(RouterLinkStub).props("to")).toBe("/admin");
    await wrapper.find("input[type=url]").setValue("https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOp");
    expect(wrapper.find("button[type=submit]").attributes("disabled")).toBeDefined();
  });

  it("tells editors that only an admin adds Notion and Google Drive sources", async () => {
    const queue = [{ items: [] }];
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        Promise.resolve(
          url === "/api/v1/connections"
            ? Response.json({ signal: "api_key_scope_missing" }, { status: 403 })
            : Response.json(queue.shift()),
        ),
      ),
    );
    const wrapper = mount(WebsiteSources, { props: { project: "demo" }, global: { stubs: { RouterLink: RouterLinkStub } } });
    await flushPromises();

    await wrapper.findAll("select")[0]!.setValue("notion");
    expect(wrapper.find(".no-connection").text()).toBe("Only an admin adds Notion and Google Drive sources.");
    expect(wrapper.find("button[type=submit]").attributes("disabled")).toBeDefined();
  });
});
