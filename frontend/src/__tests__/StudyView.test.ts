import { flushPromises, mount, RouterLinkStub } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";

import StudyView from "@/views/project/StudyView.vue";

vi.mock("@/composables/useProject", () => ({
  useProject: () => ({
    name: ref("demo"),
    files: ref([
      { file_id: "a1_guide.pdf", original_name: "guide.pdf" },
      { file_id: "b2_notes.txt", original_name: "notes.txt" },
    ]),
  }),
}));

const BASE = {
  file_id: "a1_guide.pdf",
  original_name: "guide.pdf",
  sources: [
    { number: 1, chunk_index: 0, page: 3, section: null, text: "Cats purr when content." },
    { number: 2, chunk_index: 4, page: null, section: "Kittens > Care", text: "Kittens purr while nursing." },
  ],
  prompt_version: "study-v1",
  usage: { input_tokens: 1200, output_tokens: 40, cost_usd: 0.0012 },
  passages: 5,
  chunks: 5,
};

afterEach(() => vi.unstubAllGlobals());

/** Answers the study request with `body`, and the project's decks with `decks`. */
function respond(body: unknown, decks: unknown[] = []) {
  const fetch = vi.fn((url: string, _init?: RequestInit) =>
    Promise.resolve(Response.json(String(url).includes("/decks") ? decks : body)),
  );
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

function mountView() {
  return mount(StudyView, { global: { stubs: { RouterLink: RouterLinkStub, ChunkDrawer: true, StudyDecks: true } } });
}

async function write(wrapper: ReturnType<typeof mountView>, kind: string) {
  await wrapper.find(`input[value="${kind}"]`).setValue(true);
  await wrapper.find("form").trigger("submit");
  await flushPromises();
}

describe("StudyView", () => {
  it("asks for the chosen document, kind and count", async () => {
    const fetch = respond({ ...BASE, kind: "summary", items: [] });
    const wrapper = mountView();
    await wrapper.find("select").setValue("b2_notes.txt");
    await wrapper.findAll("select")[1]!.setValue("5");
    await write(wrapper, "summary");

    const [url, init] = fetch.mock.calls[0]!;
    expect(String(url)).toContain("/api/v1/study/demo");
    expect(JSON.parse(String(init!.body))).toEqual({ file_id: "b2_notes.txt", kind: "summary", count: 5 });
    expect(wrapper.text()).toContain("The model wrote nothing usable");
  });

  it("lists key points with links to their pages and sections", async () => {
    respond({ ...BASE, kind: "summary", items: [{ text: "Cats purr when content.", sources: [1, 2] }] });
    const wrapper = mountView();
    await write(wrapper, "summary");

    expect(wrapper.find("h3").text()).toBe("Summary of guide.pdf");
    expect(wrapper.findAll(".points li")).toHaveLength(1);
    const cites = wrapper.findAll(".cite");
    expect(cites.map((cite) => cite.text())).toEqual(["p. 3", "Kittens > Care"]);
    await cites[1]!.trigger("click");
    expect(wrapper.findComponent({ name: "ChunkDrawer" }).props("focusChunk")).toBe(4);
  });

  it("turns flashcards over one by one or all at once", async () => {
    respond({
      ...BASE,
      kind: "flashcards",
      items: [
        { front: "When do cats purr?", back: "When content.", sources: [1] },
        { front: "When do kittens purr?", back: "While nursing.", sources: [2] },
      ],
    });
    const wrapper = mountView();
    await write(wrapper, "flashcards");

    const faces = wrapper.findAll(".face");
    expect(wrapper.text()).not.toContain("When content.");
    await faces[0]!.trigger("click");
    expect(faces[0]!.attributes("aria-expanded")).toBe("true");
    expect(wrapper.text()).toContain("When content.");
    expect(wrapper.text()).not.toContain("While nursing.");

    await wrapper.find(".result-head .btn").trigger("click");
    expect(wrapper.text()).toContain("While nursing.");
    expect(wrapper.find(".result-head .btn").text()).toBe("Hide the answers");
  });

  it("saves flashcards to a new deck, with where each card comes from", async () => {
    const fetch = respond({
      ...BASE,
      kind: "flashcards",
      items: [
        { front: "When do cats purr?", back: "When content.", sources: [1] },
        { front: "When do kittens purr?", back: "While nursing.", sources: [2] },
      ],
    });
    const wrapper = mountView();
    await write(wrapper, "flashcards");

    expect((wrapper.find(".save input").element as HTMLInputElement).value).toBe("guide.pdf flashcards");
    await wrapper.find(".save input").setValue("Cats");
    await wrapper.find(".save").trigger("submit");
    await flushPromises();

    const [, init] = fetch.mock.calls.find(([url, options]) => url.endsWith("/projects/demo/decks") && options?.method === "POST")!;
    expect(JSON.parse(String(init!.body))).toEqual({
      name: "Cats",
      cards: [
        { front: "When do cats purr?", back: "When content.", file_id: "a1_guide.pdf", chunk_index: 0, page: 3, section: null },
        { front: "When do kittens purr?", back: "While nursing.", file_id: "a1_guide.pdf", chunk_index: 4, page: null, section: "Kittens > Care" },
      ],
    });
    expect(wrapper.find(".save button").attributes("disabled")).toBeDefined();
  });

  it("adds flashcards to a deck the project has", async () => {
    const deck = { id: "d-1", name: "Cats", cards: 4, due: 1, created_at: "2026-10-18T10:00:00Z" };
    const fetch = respond({ ...BASE, kind: "flashcards", items: [{ front: "Q", back: "A", sources: [1] }] }, [deck]);
    const wrapper = mountView();
    await write(wrapper, "flashcards");

    await wrapper.find(".save select").setValue("d-1");
    expect(wrapper.find(".save input").exists()).toBe(false);
    await wrapper.find(".save").trigger("submit");
    await flushPromises();

    expect(fetch.mock.calls.some(([url]) => String(url).endsWith("/projects/demo/decks/d-1/cards"))).toBe(true);
  });

  it("marks quiz answers, explains them and keeps the score", async () => {
    const question = {
      question: "When do cats purr?",
      choices: ["When content", "When wet", "When hungry", "Never"],
      answer: 0,
      explanation: "Passage 1 says so.",
      sources: [1],
    };
    respond({ ...BASE, kind: "quiz", items: [question, { ...question, question: "Again?", answer: 2 }] });
    const wrapper = mountView();
    await write(wrapper, "quiz");

    const [first, second] = wrapper.findAll(".question");
    await first!.findAll(".choice")[0]!.trigger("click");
    await second!.findAll(".choice")[1]!.trigger("click");

    expect(first!.find(".choice.right").text()).toContain("When content");
    expect(first!.text()).toContain("Right. Passage 1 says so.");
    expect(second!.find(".choice.wrong").text()).toContain("When wet");
    expect(second!.find(".choice.right").text()).toContain("When hungry");
    expect(second!.text()).toContain("Not quite.");
    expect(second!.findAll(".choice").every((choice) => choice.attributes("disabled") !== undefined)).toBe(true);
    expect(wrapper.find(".score").text()).toContain("1 right of 2 answered");

    await wrapper.find(".score .btn").trigger("click");
    expect(wrapper.find(".explanation").exists()).toBe(false);
  });

  it("says when only part of a long document was used", async () => {
    respond({ ...BASE, kind: "summary", items: [{ text: "Point.", sources: [1] }], passages: 21, chunks: 40 });
    const wrapper = mountView();
    await write(wrapper, "summary");

    expect(wrapper.text()).toContain("21 of its 40 passages");
  });

  it("points to processing when the document has no chunks yet", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(Response.json({ signal: "file_not_processed" }, { status: 409 }))));
    const wrapper = mountView();
    await write(wrapper, "quiz");

    expect(wrapper.find('[role="alert"]').text()).toContain("Process it on the");
    expect(wrapper.findComponent(RouterLinkStub).props("to")).toEqual({ name: "documents", params: { project: "demo" } });
  });
});
