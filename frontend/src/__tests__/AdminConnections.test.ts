import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { reactive } from "vue";

import AdminConnections from "@/components/AdminConnections.vue";
import { useToasts } from "@/composables/useToasts";

const route = reactive({ query: {} as Record<string, string> });
const replace = vi.fn();
vi.mock("vue-router", () => ({ useRoute: () => route, useRouter: () => ({ replace }) }));
const goTo = vi.fn();
vi.mock("@/lib/navigate", () => ({ goTo: (url: string) => goTo(url) }));

const NOTION = {
  id: "con_aaaaaaaaaaaaaaaaaaaaaa",
  kind: "notion",
  account: "Acme wiki",
  created_by: "ada@example.com",
  sources_count: 2,
  created_at: "2026-10-28T10:00:00Z",
  last_error: null,
  last_error_at: null,
};
const DRIVE = {
  ...NOTION,
  id: "con_bbbbbbbbbbbbbbbbbbbbbb",
  kind: "google_drive",
  account: "ada@example.com",
  sources_count: 0,
  last_error: "Google refused the sign-in: Token has been revoked.",
};

beforeEach(() => {
  route.query = {};
  replace.mockReset();
  goTo.mockReset();
});
afterEach(() => vi.unstubAllGlobals());

function serve(items: unknown[], available = ["notion", "google_drive"]) {
  const fetch = vi.fn((_url: string, init?: RequestInit) => {
    if (init?.method === "POST") return Promise.resolve(Response.json({ authorize_url: "https://api.notion.com/v1/oauth/authorize?state=s" }));
    if (init?.method === "DELETE") return Promise.resolve(new Response(null, { status: 204 }));
    return Promise.resolve(Response.json({ items, available, redirect_uri: "https://r.example/api/v1/connections/callback" }));
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

describe("AdminConnections", () => {
  it("lists the connections, with their sources and problems", async () => {
    serve([NOTION, DRIVE]);
    const wrapper = mount(AdminConnections);
    await flushPromises();

    const [notion, drive] = wrapper.findAll(".item");
    expect(notion!.text()).toContain("Acme wiki");
    expect(notion!.text()).toContain("by ada@example.com · 2 sources");
    // A connection that sources use cannot be removed.
    expect(notion!.find("button").attributes("disabled")).toBeDefined();
    expect(drive!.find(".error").text()).toContain("Token has been revoked.. Connect Google Drive again");
    expect(wrapper.text()).toContain("https://r.example/api/v1/connections/callback");
  });

  it("sends the admin to the service to sign in, and back here", async () => {
    const fetch = serve([]);
    const wrapper = mount(AdminConnections);
    await flushPromises();

    const button = wrapper.findAll(".service button")[0]!;
    expect(button.text()).toBe("Connect Notion");
    await button.trigger("click");
    await flushPromises();

    const [url, init] = fetch.mock.calls.find(([, i]) => i?.method === "POST")!;
    expect(url).toBe("/api/v1/connections");
    expect(JSON.parse(String(init!.body))).toEqual({ kind: "notion", return_to: window.location.href.split("?")[0] });
    expect(goTo).toHaveBeenCalledWith("https://api.notion.com/v1/oauth/authorize?state=s");
  });

  it("offers only the services the server is set up for", async () => {
    serve([], ["notion"]);
    const wrapper = mount(AdminConnections);
    await flushPromises();

    const drive = wrapper.findAll(".service")[1]!;
    expect(drive.text()).toContain("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET");
    expect(drive.find("button").attributes("disabled")).toBeDefined();
  });

  it("says how the sign-in went, and takes it out of the address", async () => {
    route.query = { connected: NOTION.id, tab: "x" };
    serve([NOTION]);
    mount(AdminConnections);
    await flushPromises();
    expect(useToasts().toasts.value.at(-1)).toMatchObject({ kind: "success", message: "Notion: Acme wiki." });
    expect(replace).toHaveBeenCalledWith({ query: { tab: "x" } });

    route.query = { connection_error: "connection_denied" };
    mount(AdminConnections);
    await flushPromises();
    expect(useToasts().toasts.value.at(-1)).toMatchObject({ kind: "error", title: "Nothing was connected" });
  });

  it("removes a connection after confirming", async () => {
    const fetch = serve([DRIVE]);
    vi.stubGlobal("confirm", () => true);
    const wrapper = mount(AdminConnections);
    await flushPromises();

    await wrapper.find('button[aria-label="Remove ada@example.com"]').trigger("click");
    await flushPromises();
    const [url] = fetch.mock.calls.find(([, i]) => i?.method === "DELETE")!;
    expect(url).toBe(`/api/v1/connections/${DRIVE.id}`);
    expect(wrapper.emitted("changed")).toHaveLength(1);
  });
});
