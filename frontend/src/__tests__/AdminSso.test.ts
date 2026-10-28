import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminSso from "@/components/AdminSso.vue";

const PROVIDER = {
  issuer: "https://login.microsoftonline.com/t/v2.0",
  client_id: "ragolex",
  default_role: "editor",
  enabled: true,
  required: false,
  created_at: "2026-10-28T10:00:00Z",
  updated_at: "2026-10-28T10:00:00Z",
};

afterEach(() => vi.unstubAllGlobals());

function serve(provider: unknown, domains = ["acme.com"]) {
  const settings = (p: unknown) => ({ provider: p, redirect_uri: "https://r.example/api/v1/auth/sso/callback", email_domains: domains });
  const fetch = vi.fn((_url: string, init?: RequestInit) => {
    if (init?.method === "PUT") return Promise.resolve(Response.json(settings(PROVIDER)));
    if (init?.method === "DELETE") return Promise.resolve(new Response(null, { status: 204 }));
    return Promise.resolve(Response.json(settings(provider)));
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

describe("AdminSso", () => {
  it("sets the provider, with its secret the first time", async () => {
    const fetch = serve(null);
    const wrapper = mount(AdminSso, { props: { myRole: "admin" } });
    await flushPromises();

    expect(wrapper.text()).toContain("Emails on acme.com sign in through it.");
    expect(wrapper.text()).toContain("https://r.example/api/v1/auth/sso/callback");
    expect(wrapper.find('input[type="password"]').attributes("required")).toBeDefined();
    await wrapper.find('input[type="url"]').setValue(PROVIDER.issuer);
    await wrapper.findAll("input.mono")[1]!.setValue("ragolex");
    await wrapper.find('input[type="password"]').setValue("s3cret");
    await wrapper.find("select").setValue("editor");
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    const [, init] = fetch.mock.calls.find(([, i]) => i?.method === "PUT")!;
    expect(JSON.parse(String(init!.body))).toEqual({
      issuer: PROVIDER.issuer,
      client_id: "ragolex",
      client_secret: "s3cret",
      default_role: "editor",
      enabled: true,
      required: false,
    });
    expect(wrapper.emitted("changed")).toHaveLength(1);
  });

  it("keeps the saved secret when it is left empty, and warns without a verified domain", async () => {
    const fetch = serve(PROVIDER, []);
    const wrapper = mount(AdminSso, { props: { myRole: "admin" } });
    await flushPromises();

    expect(wrapper.find(".alert-warning").text()).toContain("verify it first");
    expect(wrapper.find('input[type="password"]').attributes("required")).toBeUndefined();
    await wrapper.find("form").trigger("submit");
    await flushPromises();
    const [, init] = fetch.mock.calls.find(([, i]) => i?.method === "PUT")!;
    expect(JSON.parse(String(init!.body))).not.toHaveProperty("client_secret");
  });

  it("lets only an owner require it", async () => {
    const fetch = serve(PROVIDER);
    const admin = mount(AdminSso, { props: { myRole: "admin" } });
    await flushPromises();
    const box = () => admin.findAll('input[type="checkbox"]')[1]!;
    expect(box().attributes("disabled")).toBeDefined();
    expect(admin.text()).toContain("Only an owner turns this on or off.");

    const owner = mount(AdminSso, { props: { myRole: "owner" } });
    await flushPromises();
    const required = owner.findAll('input[type="checkbox"]')[1]!;
    expect(required.attributes("disabled")).toBeUndefined();
    expect(owner.text()).toContain("Owners keep their passwords");
    await required.setValue(true);
    await owner.find("form").trigger("submit");
    await flushPromises();
    const [, init] = fetch.mock.calls.find(([, i]) => i?.method === "PUT")!;
    expect(JSON.parse(String(init!.body))).toMatchObject({ required: true });
  });

  it("removes it after confirming", async () => {
    const fetch = serve(PROVIDER);
    vi.stubGlobal("confirm", () => true);
    const wrapper = mount(AdminSso, { props: { myRole: "admin" } });
    await flushPromises();

    await wrapper.findAll("button").find((b) => b.text() === "Remove")!.trigger("click");
    await flushPromises();
    expect(fetch.mock.calls.some(([, i]) => i?.method === "DELETE")).toBe(true);
  });
});
