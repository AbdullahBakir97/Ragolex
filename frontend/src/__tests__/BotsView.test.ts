import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";

import type { ChatBot } from "@/api/types";
import BotsView from "@/views/project/BotsView.vue";

vi.mock("@/composables/useProject", () => ({
  useProject: () => ({ name: ref("demo"), tags: ref([{ tag: "hr", files: 2 }]) }),
}));

function bot(overrides: Partial<ChatBot> = {}): ChatBot {
  return {
    id: "bot_aaaaaaaaaaaaaaaaaaaaaa",
    project: "demo",
    kind: "telegram",
    name: "Help desk",
    account: "@acme_help_bot",
    tags: [],
    enabled: true,
    webhook_url: "https://ragolex.example.com/api/v1/bots/bot_aaaaaaaaaaaaaaaaaaaaaa/webhook",
    verify_token: null,
    created_at: "2026-10-01T10:00:00Z",
    last_message_at: null,
    last_error: null,
    last_error_at: null,
    ...overrides,
  };
}

afterEach(() => vi.unstubAllGlobals());

/** Serves the project's bots from `listed`, and `created` for a new one. */
function serve(listed: ChatBot[], created?: ChatBot) {
  const fetch = vi.fn((_url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (method === "POST") return Promise.resolve(Response.json(created, { status: 201 }));
    if (method === "PATCH") return Promise.resolve(Response.json(listed[0]));
    if (method === "DELETE") return Promise.resolve(new Response(null, { status: 204 }));
    return Promise.resolve(Response.json({ items: listed }));
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

function calls(fetch: ReturnType<typeof serve>, method: string) {
  return fetch.mock.calls.filter(([, init]) => (init?.method ?? "GET") === method);
}

describe("BotsView", () => {
  it("says so when the project has no bots", async () => {
    serve([]);
    const wrapper = mount(BotsView);
    await flushPromises();
    expect(wrapper.text()).toContain("No bots yet");
  });

  it("adds a Telegram bot with its token and tags", async () => {
    const added = bot({ tags: ["hr"] });
    const fetch = serve([], added);
    const wrapper = mount(BotsView);
    await flushPromises();

    const button = wrapper.find('button[type="submit"]');
    expect(button.attributes("disabled")).toBeDefined();
    await wrapper.find('input[placeholder="Help desk"]').setValue("Help desk");
    await wrapper.find('input[type="password"]').setValue(" 123:AAtoken ");
    expect(button.attributes("disabled")).toBeUndefined();
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    const [url, init] = calls(fetch, "POST")[0]!;
    expect(String(url)).toContain("/api/v1/projects/demo/bots");
    expect(JSON.parse(String(init!.body))).toEqual({
      kind: "telegram",
      name: "Help desk",
      credentials: { token: "123:AAtoken" },
      tags: [],
    });
    expect(wrapper.find('[role="status"]').text()).toContain("Message @acme_help_bot in Telegram to try it.");
  });

  it("asks for each chat app's own credentials", async () => {
    serve([]);
    const wrapper = mount(BotsView);
    await flushPromises();

    await wrapper.find('input[value="slack"]').setValue(true);
    expect(wrapper.findAll(".fields .field span").map((s) => s.text())).toEqual(["Name", "Bot token", "Signing secret"]);
    expect(wrapper.text()).toContain("Event Subscriptions");

    await wrapper.find('input[value="whatsapp"]').setValue(true);
    expect(wrapper.findAll(".fields .field span").map((s) => s.text())).toEqual([
      "Name",
      "Access token",
      "Phone number ID",
      "App secret",
    ]);
    // The phone number ID is not a secret.
    expect(wrapper.findAll(".fields input").map((i) => i.attributes("type") ?? "text")).toEqual([
      "text",
      "password",
      "text",
      "password",
    ]);
  });

  it("shows the webhook URL and verify token a WhatsApp bot needs", async () => {
    serve([bot({ kind: "whatsapp", name: "Support", account: "+1 555 0100", verify_token: "vt-123" })]);
    const writeText = vi.fn(() => Promise.resolve());
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    const wrapper = mount(BotsView);
    await flushPromises();

    const card = wrapper.find('li[aria-label="Support"]');
    expect(card.text()).toContain("/api/v1/bots/bot_aaaaaaaaaaaaaaaaaaaaaa/webhook");
    expect(card.text()).toContain("vt-123");
    await card.find('button[aria-label="Copy the verify token of Support"]').trigger("click");
    expect(writeText).toHaveBeenCalledWith("vt-123");
  });

  it("does not show a webhook for Telegram, which connects itself", async () => {
    serve([bot()]);
    const wrapper = mount(BotsView);
    await flushPromises();
    expect(wrapper.find("dl.setup").exists()).toBe(false);
  });

  it("shows a bot's last problem", async () => {
    serve([bot({ last_error: "Telegram refused the message." })]);
    const wrapper = mount(BotsView);
    await flushPromises();
    expect(wrapper.text()).toContain("Last problem: Telegram refused the message.");
  });

  it("turns a bot off and removes it after confirming", async () => {
    const fetch = serve([bot()]);
    const wrapper = mount(BotsView);
    await flushPromises();

    await wrapper.find('input[type="checkbox"]').setValue(false);
    await flushPromises();
    const [url, init] = calls(fetch, "PATCH")[0]!;
    expect(String(url)).toContain("/api/v1/projects/demo/bots/bot_aaaaaaaaaaaaaaaaaaaaaa");
    expect(JSON.parse(String(init!.body))).toEqual({ enabled: false });

    await wrapper.find('button[aria-label="Remove Help desk"]').trigger("click");
    expect(calls(fetch, "DELETE")).toHaveLength(0);
    const confirm = wrapper.findAll("button").find((b) => b.text() === "Remove")!;
    await confirm.trigger("click");
    await flushPromises();
    expect(calls(fetch, "DELETE")).toHaveLength(1);
  });
});
