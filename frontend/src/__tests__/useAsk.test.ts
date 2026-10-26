import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";

import type { ConversationMessage } from "@/api/types";
import { type AskSettings, turnsFrom, useAsk } from "@/composables/useAsk";

const CITATION = { number: 1, file_id: "a_guide.txt", chunk_index: 2, page: null, score: 0.9, text: "Cats purr." };

let nextMessageId = 1;

function message(
  role: ConversationMessage["role"],
  content: string | null,
  extra: Partial<ConversationMessage> = {},
): ConversationMessage {
  return {
    id: nextMessageId++,
    role,
    content,
    citations: [],
    prompt_version: null,
    search_question: null,
    created_at: "2026-10-18T10:00:00Z",
    feedback: null,
    ...extra,
  };
}

function answer(text: string, extra: Record<string, unknown> = {}) {
  return {
    signal: "answer_success",
    answer: text,
    citations: [],
    prompt_version: "answer-v1",
    usage: { input_tokens: 10, output_tokens: 5, cost_usd: 0 },
    conversation_id: "c-1",
    search_question: null,
    ...extra,
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("turnsFrom", () => {
  it("pairs stored questions with their answers", () => {
    const turns = turnsFrom(
      [
        message("user", "Do cats purr?"),
        message("assistant", "Yes [1].", { citations: [CITATION], prompt_version: "answer-v1" }),
        message("user", "And dogs?"),
        message("assistant", null, { prompt_version: "answer-v1", search_question: "Do dogs purr?" }),
      ],
      "c-1",
    );

    expect(turns.map((turn) => [turn.question, turn.status, turn.text, turn.stored])).toEqual([
      ["Do cats purr?", "done", "Yes [1].", true],
      ["And dogs?", "done", "", true],
    ]);
    expect(turns[0]!.answer).toMatchObject({ signal: "answer_success", citations: [CITATION], conversation_id: "c-1" });
    expect(turns[1]!.answer).toMatchObject({ signal: "no_answer", answer: null, search_question: "Do dogs purr?" });
  });
});

describe("useAsk", () => {
  const settings = ref<AskSettings>({ top_k: 5, min_score: null, stream: false });

  it("starts a conversation with the first question and follows up in it", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(Response.json({ id: "c-1", title: null }, { status: 201 }))
      .mockResolvedValueOnce(Response.json(answer("Yes [1].")))
      .mockResolvedValueOnce(Response.json(answer("No.", { search_question: "Do dogs purr?" })));
    vi.stubGlobal("fetch", fetch);
    const conversation = ref<string | null>(null);
    const started = vi.fn((id: string) => (conversation.value = id));
    const { turns, ask } = useAsk(ref("demo"), conversation, settings, { onStarted: started });

    await ask("Do cats purr?");
    await ask("And dogs?");

    expect(started).toHaveBeenCalledExactlyOnceWith("c-1");
    const bodies = fetch.mock.calls.slice(1).map(([, init]) => JSON.parse(init.body));
    expect(bodies.map((body) => [body.question, body.conversation_id])).toEqual([
      ["Do cats purr?", "c-1"],
      ["And dogs?", "c-1"],
    ]);
    expect(turns.value.map((turn) => [turn.text, turn.answer?.search_question])).toEqual([
      ["Yes [1].", null],
      ["No.", "Do dogs purr?"],
    ]);
    // The conversation this page started is not loaded again.
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it("loads a stored conversation", async () => {
    const detail = { id: "c-2", title: "Cats", messages: [message("user", "Do cats purr?"), message("assistant", "Yes.")] };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(detail)));

    const { turns } = useAsk(ref("demo"), ref("c-2"), settings);
    await flushPromises();

    expect(turns.value.map((turn) => [turn.question, turn.text])).toEqual([["Do cats purr?", "Yes."]]);
  });

  it("reports a conversation that does not exist", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ signal: "conversation_not_found" }, { status: 404 })));
    const failed = vi.fn();

    const { turns } = useAsk(ref("demo"), ref("c-3"), settings, { onLoadFailed: failed });
    await flushPromises();

    expect(turns.value).toEqual([]);
    expect(failed).toHaveBeenCalledWith(expect.objectContaining({ signal: "conversation_not_found" }), true);
  });

  it("clears the turns for a new conversation", async () => {
    const detail = { id: "c-2", title: "Cats", messages: [message("user", "Do cats purr?"), message("assistant", "Yes.")] };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(detail)));
    const conversation = ref<string | null>("c-2");
    const { turns } = useAsk(ref("demo"), conversation, settings);
    await flushPromises();

    conversation.value = null;
    await flushPromises();

    expect(turns.value).toEqual([]);
  });
});

describe("useAsk while a conversation is being started", () => {
  it("stays on a conversation opened meanwhile", async () => {
    let created!: (response: Response) => void;
    const detail = { id: "c-2", title: "Cats", messages: [message("user", "Do cats purr?"), message("assistant", "Yes.")] };
    const fetch = vi
      .fn()
      .mockReturnValueOnce(new Promise<Response>((resolve) => (created = resolve)))
      .mockResolvedValueOnce(Response.json(detail));
    vi.stubGlobal("fetch", fetch);
    const conversation = ref<string | null>(null);
    const started = vi.fn();
    const settings = ref<AskSettings>({ top_k: 5, min_score: null, stream: false });
    const { turns, ask } = useAsk(ref("demo"), conversation, settings, { onStarted: started });

    const asking = ask("Do dogs purr?");
    conversation.value = "c-2";
    await flushPromises();
    created(Response.json({ id: "c-1", title: null }, { status: 201 }));
    await asking;
    await flushPromises();

    expect(started).not.toHaveBeenCalled();
    expect(turns.value.map((turn) => turn.question)).toEqual(["Do cats purr?"]);
    expect(fetch).toHaveBeenCalledTimes(2);
  });
});

describe("rating answers", () => {
  const settings = ref<AskSettings>({ top_k: 5, min_score: null, stream: false });
  const detail = {
    id: "c-2",
    title: "Cats",
    messages: [message("user", "Do cats purr?"), message("assistant", "Yes.", { id: 42 })],
  };

  it("shows a rating at once and saves it", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(Response.json(detail))
      .mockResolvedValueOnce(Response.json({ id: 42 }));
    vi.stubGlobal("fetch", fetch);
    const { turns, rate } = useAsk(ref("demo"), ref("c-2"), settings);
    await flushPromises();

    const saving = rate(turns.value[0]!, "up");
    expect(turns.value[0]!.feedback?.rating).toBe("up");
    await saving;

    expect(fetch.mock.calls[1]![0]).toBe("/api/v1/projects/demo/conversations/c-2/messages/42/feedback");
  });

  it("puts the rating back when it cannot be saved", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(Response.json(detail))
        .mockResolvedValueOnce(Response.json({ signal: "message_not_found" }, { status: 404 })),
    );
    const { turns, rate } = useAsk(ref("demo"), ref("c-2"), settings);
    await flushPromises();

    await expect(rate(turns.value[0]!, "down", "Wrong.")).rejects.toMatchObject({ signal: "message_not_found" });
    expect(turns.value[0]!.feedback).toBeNull();
  });
});

describe("asking from some documents", () => {
  it("sends the chosen files as a filter", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(Response.json({ id: "c-1", title: null }, { status: 201 }))
      .mockResolvedValueOnce(Response.json(answer("Yes [1].")));
    vi.stubGlobal("fetch", fetch);
    const settings = ref<AskSettings>({ top_k: 5, min_score: null, stream: false, files: ["a_guide.pdf"] });
    const { ask } = useAsk(ref("demo"), ref<string | null>(null), settings);

    await ask("Do cats purr?");

    expect(JSON.parse(fetch.mock.calls[1]![1].body).filters).toEqual({ file_ids: ["a_guide.pdf"] });
  });
});


describe("research mode", () => {
  it("is asked for only when it is on", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(Response.json({ id: "c-1", title: null }, { status: 201 }))
      .mockResolvedValueOnce(Response.json(answer("Yes [1].")))
      .mockResolvedValueOnce(Response.json(answer("No [1].")));
    vi.stubGlobal("fetch", fetch);
    const settings = ref<AskSettings>({ top_k: 5, min_score: null, stream: false, research: true });
    const { ask } = useAsk(ref("demo"), ref<string | null>(null), settings);

    await ask("Do cats purr and dogs bark?");
    settings.value.research = false;
    await ask("And birds?");

    expect(JSON.parse(fetch.mock.calls[1]![1].body).research).toBe(true);
    expect(JSON.parse(fetch.mock.calls[2]![1].body)).not.toHaveProperty("research");
  });
});
