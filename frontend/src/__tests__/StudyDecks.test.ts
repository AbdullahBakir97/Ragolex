import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import StudyDecks from "@/components/StudyDecks.vue";

const DECK = { id: "d-1", name: "Cats", cards: 2, due: 2, created_at: "2026-10-18T10:00:00Z" };
const intervals = { again: 10 / 1440, hard: 1, good: 3, easy: 45 };
function card(id: string, front: string, back: string, page: number | null = null) {
  return {
    id,
    front,
    back,
    source: { file_id: "a1_cats.pdf", chunk_index: 0, page, section: null },
    due_at: "2026-10-18T09:00:00Z",
    interval_days: 0,
    ease: 2.5,
    repetitions: 0,
    lapses: 0,
    last_reviewed_at: null,
    created_at: "2026-10-18T09:00:00Z",
    intervals,
  };
}
const QUEUE = { deck: DECK, cards: [card("c-1", "When do cats purr?", "When content.", 3), card("c-2", "Kittens?", "Purr too.")] };

afterEach(() => vi.unstubAllGlobals());

/** Answers each request by its method and path. */
function serve(routes: Record<string, () => Response>) {
  const fetch = vi.fn((url: string, init?: RequestInit) => {
    const path = new URL(String(url), "http://localhost").pathname.replace("/api/v1/projects/demo/decks", "");
    const handler = routes[`${init?.method ?? "GET"} ${path}`];
    return Promise.resolve(handler ? handler() : Response.json({ signal: "not_mocked" }, { status: 500 }));
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

async function mountDecks() {
  const wrapper = mount(StudyDecks, { props: { project: "demo" }, attachTo: document.body });
  await flushPromises();
  return wrapper;
}

describe("StudyDecks", () => {
  it("lists the decks with what is due", async () => {
    serve({ "GET ": () => Response.json([DECK, { ...DECK, id: "d-2", name: "Dogs", cards: 1, due: 0 }]) });
    const wrapper = await mountDecks();

    const decks = wrapper.findAll(".deck");
    expect(decks.map((deck) => deck.find(".deck-name").text())).toEqual(["Cats2 cards", "Dogs1 card"]);
    expect(decks[0]!.find(".badge").text()).toBe("2 due");
    expect(decks[1]!.find(".btn-primary").attributes("disabled")).toBeDefined();
    wrapper.unmount();
  });

  it("says when there are no decks, also for a new project", async () => {
    serve({ "GET ": () => Response.json({ signal: "project_not_found" }, { status: 404 }) });
    const wrapper = await mountDecks();

    expect(wrapper.text()).toContain("No decks yet");
    wrapper.unmount();
  });

  it("reviews the due cards with the keyboard, showing when each grade brings them back", async () => {
    let reviews = 0;
    const fetch = serve({
      "GET ": () => Response.json([DECK]),
      // Then nothing is due: a card graded "again" comes back in minutes.
      "GET /d-1/review": () => Response.json(reviews++ ? { deck: DECK, cards: [] } : QUEUE),
      "POST /d-1/cards/c-1/review": () => Response.json(card("c-1", "", "")),
      "POST /d-1/cards/c-2/review": () => Response.json(card("c-2", "", "")),
    });
    const wrapper = await mountDecks();
    await wrapper.find(".deck .btn-primary").trigger("click");
    await flushPromises();

    expect(wrapper.find(".front").text()).toBe("When do cats purr?");
    expect(wrapper.find(".back").exists()).toBe(false);
    window.dispatchEvent(new KeyboardEvent("keydown", { key: " " }));
    await flushPromises();
    expect(wrapper.find(".back").text()).toBe("When content.");
    expect(wrapper.text()).toContain("Page 3");
    expect(wrapper.findAll(".grade").map((button) => button.text())).toEqual([
      "Again 110 min",
      "Hard 21 day",
      "Good 33 days",
      "Easy 42 mo",
    ]);

    window.dispatchEvent(new KeyboardEvent("keydown", { key: "3" }));
    await flushPromises();
    const [, init] = fetch.mock.calls.find(([url]) => String(url).endsWith("/cards/c-1/review"))!;
    expect(JSON.parse(String(init!.body))).toEqual({ grade: "good" });
    expect(wrapper.find(".front").text()).toBe("Kittens?");
    // Grades need the answer shown first.
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "1" }));
    await flushPromises();
    expect(fetch.mock.calls.some(([url]) => String(url).endsWith("/cards/c-2/review"))).toBe(false);

    await wrapper.find(".reveal").trigger("click");
    await wrapper.findAll(".grade")[0]!.trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("All caught up");
    expect(wrapper.text()).toContain("2 reviewed");
    wrapper.unmount();
  });

  it("exports a deck to a file for Anki", async () => {
    serve({
      "GET ": () => Response.json([DECK]),
      "GET /d-1/anki": () =>
        new Response("#separator:tab\n", { headers: { "Content-Disposition": 'attachment; filename="Cats.txt"' } }),
    });
    const clicked: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this.download);
    });
    URL.createObjectURL = vi.fn(() => "blob:deck");
    URL.revokeObjectURL = vi.fn();
    const wrapper = await mountDecks();

    await wrapper.find('[aria-label="Export Cats to Anki"]').trigger("click");
    await flushPromises();

    expect(clicked).toEqual(["Cats.txt"]);
    wrapper.unmount();
  });

  it("deletes a deck once confirmed", async () => {
    const fetch = serve({ "GET ": () => Response.json([DECK]), "DELETE /d-1": () => new Response(null, { status: 204 }) });
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    const wrapper = await mountDecks();

    await wrapper.find('[aria-label="Delete Cats"]').trigger("click");
    expect(fetch.mock.calls.filter(([, init]) => init?.method === "DELETE")).toHaveLength(0);
    await wrapper.find('[aria-label="Delete Cats"]').trigger("click");
    await flushPromises();

    expect(confirm).toHaveBeenCalledTimes(2);
    expect(wrapper.findAll(".deck")).toHaveLength(0);
    wrapper.unmount();
  });
});
