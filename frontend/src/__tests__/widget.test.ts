import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WidgetClient, WidgetError, failureMessage } from "@/widget/client";
import { renderAnswer, sourceLabel, textOn } from "@/widget/render";
import { ChatWidget } from "@/widget/widget";

const CONFIG = { id: "wgt_1", name: "Helper", welcome: "Ask me about the guide.", accent: "#0f766e" };
const CITATION = { number: 1, file_name: "guide.pdf", page: 3, section: "Setup", text: "Chunks are embedded." };

function sse(...events: [string, unknown][]): Response {
  const body = events.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join("");
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

function answer(text: string | null, extra: Record<string, unknown> = {}) {
  return {
    signal: text === null ? "no_answer" : "answer_success",
    answer: text,
    citations: text === null ? [] : [CITATION],
    conversation_id: "c-1",
    message_id: 7,
    ...extra,
  };
}

class MemoryStorage {
  items = new Map<string, string>();
  getItem(key: string) {
    return this.items.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.items.set(key, value);
  }
}

async function settle() {
  for (let i = 0; i < 10; i++) await new Promise((resolve) => setTimeout(resolve, 0));
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.replaceChildren();
});

describe("rendering", () => {
  it("never turns the model's text into markup", () => {
    const fragment = renderAnswer('<img src=x onerror="alert(1)"> **Bold** [1]', () => null);
    const holder = document.createElement("div");
    holder.append(fragment);

    expect(holder.querySelector("img")).toBeNull();
    expect(holder.querySelector("strong")?.textContent).toBe("Bold");
    expect(holder.textContent).toBe('<img src=x onerror="alert(1)"> Bold [1]');
  });

  it("names a source by its document, page and section", () => {
    expect(sourceLabel(CITATION)).toBe("guide.pdf · p. 3 · Setup");
    expect(sourceLabel({ file_name: null, page: null, section: null })).toBe("Document");
  });

  it("picks the readable text colour for an accent", () => {
    expect(textOn("#2563eb")).toBe("#ffffff");
    expect(textOn("#fde047")).toBe("#111827");
  });
});

describe("WidgetClient", () => {
  it("asks without a conversation the first time, and streams the answer", async () => {
    const fetch = vi.fn().mockResolvedValue(sse(["delta", { text: "Hi" }], ["answer", answer("Hi")]));
    vi.stubGlobal("fetch", fetch);

    const events = [];
    for await (const event of new WidgetClient("https://rag.example/", "wgt_1").ask("Q?", null)) events.push(event);

    const [url, init] = fetch.mock.calls[0]!;
    expect(url).toBe("https://rag.example/api/v1/widgets/wgt_1/ask");
    expect(JSON.parse(init.body)).toEqual({ question: "Q?" });
    expect(init.credentials).toBe("omit");
    expect(events.map((event) => event.kind)).toEqual(["delta", "answer"]);
  });

  it("reports refusals with their signal and when to retry", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(Response.json({ signal: "rate_limited" }, { status: 429, headers: { "Retry-After": "12" } })),
    );

    const error = await new WidgetClient("", "wgt_1").config().catch((caught) => caught);

    expect(error).toBeInstanceOf(WidgetError);
    expect([error.signal, error.status, error.retryAfter]).toEqual(["rate_limited", 429, 12]);
    expect(failureMessage(error)).toMatch(/Too many questions/);
  });

  it("turns an error event into a WidgetError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sse(["error", { signal: "llm_failed" }])));

    const run = async () => {
      for await (const _ of new WidgetClient("", "wgt_1").ask("Q?", "c-1")) void _;
    };

    await expect(run()).rejects.toMatchObject({ signal: "llm_failed" });
  });
});

describe("ChatWidget", () => {
  let fetch: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetch = vi.fn().mockResolvedValueOnce(Response.json(CONFIG));
    vi.stubGlobal("fetch", fetch);
    // jsdom does not lay pages out.
    Element.prototype.scrollIntoView = vi.fn();
  });

  async function mount(storage: MemoryStorage | null = null) {
    const widget = await ChatWidget.mount({ widgetId: "wgt_1", apiBase: "https://rag.example", storage: storage as Storage | null });
    const shadow = widget.host.shadowRoot!;
    return { widget, shadow };
  }

  it("shows a launcher that opens the panel with the welcome message", async () => {
    const { widget, shadow } = await mount();
    const launcher = shadow.querySelector<HTMLButtonElement>(".launcher")!;

    expect(widget.isOpen).toBe(false);
    expect(launcher.getAttribute("aria-label")).toBe("Chat: Helper");
    launcher.click();

    expect(widget.isOpen).toBe(true);
    expect(launcher.getAttribute("aria-expanded")).toBe("true");
    expect(shadow.querySelector("h2")?.textContent).toBe("Helper");
    expect(shadow.querySelector(".message.assistant")?.textContent).toBe("Ask me about the guide.");
    expect(shadow.querySelector<HTMLElement>(".root")!.style.getPropertyValue("--accent")).toBe("#0f766e");
  });

  it("shows its logo, only from an https URL", async () => {
    fetch.mockReset();
    fetch.mockResolvedValueOnce(Response.json({ ...CONFIG, logo_url: "https://example.com/logo.png" }));
    const { shadow } = await mount();

    const logo = shadow.querySelector<HTMLImageElement>("header .logo")!;
    expect(logo.getAttribute("src")).toBe("https://example.com/logo.png");
    expect(logo.getAttribute("alt")).toBe("");

    fetch.mockResolvedValueOnce(Response.json({ ...CONFIG, logo_url: "http://example.com/logo.png" }));
    const plain = await mount();
    expect(plain.shadow.querySelector("header .logo")).toBeNull();
  });

  it("streams answers, links their citations to the sources, and takes ratings", async () => {
    const storage = new MemoryStorage();
    const { widget, shadow } = await mount(storage);
    fetch.mockResolvedValueOnce(sse(["delta", { text: "Chunks are " }], ["delta", { text: "embedded [1]." }], ["answer", answer("Chunks are embedded [1].")]));
    fetch.mockResolvedValueOnce(new Response(null, { status: 204 }));

    await widget.ask("How are chunks stored?");
    const messages = shadow.querySelectorAll(".message");
    const reply = messages[2]!;
    const cite = reply.querySelector<HTMLButtonElement>("button.cite")!;
    const details = reply.querySelector<HTMLDetailsElement>("details")!;
    cite.click();
    reply.querySelector<HTMLButtonElement>('.feedback button[aria-label="Helpful"]')!.click();
    await settle();

    expect(messages[1]!.textContent).toBe("How are chunks stored?");
    expect(reply.querySelector(".body")?.textContent).toBe("Chunks are embedded 1.");
    expect(details.open).toBe(true);
    expect(details.querySelector("summary")?.textContent).toBe("[1] guide.pdf · p. 3 · Setup");
    expect(details.querySelector("blockquote")?.textContent).toBe("Chunks are embedded.");
    const [url, init] = fetch.mock.calls[2]!;
    expect(url).toBe("https://rag.example/api/v1/widgets/wgt_1/conversations/c-1/messages/7/feedback");
    expect([init.method, JSON.parse(init.body)]).toEqual(["PUT", { rating: "up" }]);
    expect(reply.querySelector('.feedback button[aria-label="Helpful"]')?.getAttribute("aria-pressed")).toBe("true");
    const saved = JSON.parse(storage.getItem("ragolex-widget:wgt_1")!);
    expect(saved.conversationId).toBe("c-1");
    expect(saved.messages[1].rating).toBe("up");
  });

  it("follows up in the conversation, and picks it up again on the next page", async () => {
    const storage = new MemoryStorage();
    const { widget } = await mount(storage);
    fetch.mockResolvedValueOnce(sse(["answer", answer("First [1].")]));
    await widget.ask("First?");
    fetch.mockResolvedValueOnce(sse(["answer", answer(null)]));
    await widget.ask("Second?");

    expect(JSON.parse(fetch.mock.calls[2]![1].body)).toEqual({ question: "Second?", conversation_id: "c-1" });

    widget.destroy();
    fetch.mockResolvedValueOnce(Response.json(CONFIG));
    const { shadow } = await mount(storage);
    const texts = [...shadow.querySelectorAll(".message")].map((message) => message.textContent);
    expect(texts[1]).toBe("First?");
    expect(texts[4]).toMatch(/couldn't find the answer/);
  });

  it("says why an answer failed, and starts over when asked", async () => {
    const { widget, shadow } = await mount();
    fetch.mockResolvedValueOnce(Response.json({ signal: "answer_quota_exceeded" }, { status: 429 }));

    await widget.ask("Anything?");
    const error = shadow.querySelector(".message.error");
    shadow.querySelector<HTMLButtonElement>('button[aria-label="New conversation"]')!.click();

    expect(error?.textContent).toMatch(/cannot answer more questions/);
    expect(shadow.querySelectorAll(".message")).toHaveLength(1);
  });

  it("refuses to load when the website is not allowed", async () => {
    fetch.mockReset().mockResolvedValueOnce(Response.json({ signal: "origin_not_allowed" }, { status: 403 }));

    await expect(mount()).rejects.toMatchObject({ signal: "origin_not_allowed" });
    expect(document.querySelector("[data-ragolex-widget]")).toBeNull();
  });
});
