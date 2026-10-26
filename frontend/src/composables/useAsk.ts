import { ref, watch, type Ref } from "vue";

import { ApiError, api } from "@/api/client";
import type { Answer, ConversationMessage, Feedback, Rating, SearchFilters, SearchOptions } from "@/api/types";

export interface Turn {
  id: number;
  question: string;
  status: "streaming" | "done" | "stopped" | "failed";
  /** The text so far while streaming; the answer's text once done. */
  text: string;
  answer: Answer | null;
  error: string | null;
  seconds: number | null;
  /** Loaded from the server: its tokens and cost were not kept with it. */
  stored: boolean;
  /** The answer's rating, once rated. */
  feedback: Feedback | null;
}

export interface AskSettings extends SearchOptions {
  stream: boolean;
  /** Research mode: the model plans the searches, for questions with several parts. */
  research?: boolean;
  /** Answer only from these files; none means all. */
  files?: string[];
  /** Answer only from files with any of these tags; none means all. */
  tags?: string[];
}

export interface AskEvents {
  /** A conversation was started by the first question asked without one. */
  onStarted?: (id: string) => void;
  /** A question was answered in the conversation, which is now the most recent. */
  onAnswered?: (id: string) => void;
  /** The conversation could not be loaded; `missing` when it does not exist. */
  onLoadFailed?: (error: ApiError, missing: boolean) => void;
}

/** Pairs a conversation's stored questions with their answers. */
export function turnsFrom(messages: ConversationMessage[], conversationId: string): Turn[] {
  const turns: Turn[] = [];
  for (const message of messages) {
    if (message.role === "user") {
      turns.push({
        id: turns.length + 1,
        question: message.content ?? "",
        status: "stopped",
        text: "",
        answer: null,
        error: null,
        seconds: null,
        stored: true,
        feedback: null,
      });
      continue;
    }
    const turn = turns.at(-1);
    if (!turn || turn.answer) continue;
    turn.status = "done";
    turn.text = message.content ?? "";
    turn.feedback = message.feedback;
    turn.answer = {
      signal: message.content === null ? "no_answer" : "answer_success",
      answer: message.content,
      citations: message.citations,
      prompt_version: message.prompt_version ?? "",
      usage: { input_tokens: null, output_tokens: null, cost_usd: null },
      conversation_id: conversationId,
      search_question: message.search_question,
      message_id: message.id,
    };
  }
  return turns;
}

/**
 * The questions and answers of one conversation of a project. With no
 * conversation, the first question starts one; every later question is
 * answered as a follow-up, and the conversation is kept on the server.
 */
export function useAsk(
  project: Ref<string>,
  conversation: Ref<string | null>,
  settings: Ref<AskSettings>,
  events: AskEvents = {},
) {
  const turns = ref<Turn[]>([]);
  const busy = ref(false);
  const loading = ref(false);
  let controller: AbortController | null = null;
  let nextId = 1;
  // The conversation the turns belong to; it differs from `conversation`
  // only while a new one is being shown or loaded.
  let current: string | null = null;
  let loadCount = 0;

  async function load(id: string | null) {
    const requested = ++loadCount;
    current = id;
    turns.value = [];
    if (!id) {
      loading.value = false;
      return;
    }
    loading.value = true;
    try {
      const detail = await api.conversation(project.value, id);
      if (requested !== loadCount) return;
      turns.value = turnsFrom(detail.messages, id);
      nextId = turns.value.length + 1;
    } catch (caught) {
      if (requested !== loadCount) return;
      const error = caught instanceof ApiError ? caught : new ApiError(0, "network_error");
      const missing = ["conversation_not_found", "project_not_found", "validation_error"].includes(error.signal);
      events.onLoadFailed?.(error, missing);
    } finally {
      if (requested === loadCount) loading.value = false;
    }
  }

  // A conversation this page just started is already shown: it is not reloaded.
  watch(
    [project, conversation],
    ([, id], previous) => {
      const projectChanged = previous && previous[0] !== project.value;
      if (!projectChanged && id === current) return;
      stop();
      void load(id);
    },
    { immediate: true },
  );

  function update(id: number, changes: Partial<Turn>) {
    turns.value = turns.value.map((turn) => (turn.id === id ? { ...turn, ...changes } : turn));
  }

  async function ask(question: string) {
    if (busy.value || loading.value || !question.trim()) return;
    const id = nextId++;
    const started = performance.now();
    const { stream, top_k, min_score, files, tags, research } = settings.value;
    turns.value = [
      ...turns.value,
      {
        id,
        question: question.trim(),
        status: "streaming",
        text: "",
        answer: null,
        error: null,
        seconds: null,
        stored: false,
        feedback: null,
      },
    ];
    busy.value = true;
    controller = new AbortController();
    const signal = controller.signal;
    const name = project.value;
    try {
      if (!current) {
        const created = await api.createConversation(name);
        // Opening another conversation meanwhile stops this question.
        if (signal.aborted) throw new DOMException("The question was stopped.", "AbortError");
        current = created.id;
        events.onStarted?.(current);
      }
      const conversationId = current;
      const filters: SearchFilters = {};
      if (files?.length) filters.file_ids = files;
      if (tags?.length) filters.tags = tags;
      const options = {
        top_k,
        min_score,
        filters: Object.keys(filters).length ? filters : null,
        conversation_id: conversationId,
        ...(research ? { research: true } : {}),
      };
      let text = "";
      const answer = stream
        ? await api.askStream(
            name,
            question,
            options,
            {
              onDelta: (piece) => {
                text += piece;
                update(id, { text });
              },
            },
            signal,
          )
        : await api.ask(name, question, options, signal);
      update(id, {
        status: "done",
        text: answer.answer ?? "",
        answer,
        seconds: (performance.now() - started) / 1000,
      });
      events.onAnswered?.(conversationId);
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") {
        update(id, { status: "stopped" });
      } else {
        update(id, {
          status: "failed",
          error: caught instanceof ApiError ? caught.message : "Something went wrong.",
        });
      }
    } finally {
      busy.value = false;
      controller = null;
    }
  }

  function stop() {
    controller?.abort();
  }

  /** Rates an answer, or removes its rating with null; the change shows at once. */
  async function rate(turn: Turn, rating: Rating | null, comment?: string) {
    const messageId = turn.answer?.message_id;
    if (!current || messageId == null) return;
    const before = turn.feedback;
    update(turn.id, {
      feedback: rating ? { rating, comment: comment?.trim() || null, created_at: new Date().toISOString() } : null,
    });
    try {
      if (rating) await api.rate(project.value, current, messageId, rating, comment);
      else await api.unrate(project.value, current, messageId);
    } catch (caught) {
      update(turn.id, { feedback: before });
      throw caught;
    }
  }

  // A failed or stopped question was not added to the conversation, so it is asked again.
  function retry(turn: Turn) {
    turns.value = turns.value.filter((candidate) => candidate.id !== turn.id);
    void ask(turn.question);
  }

  return { turns, busy, loading, ask, stop, retry, rate };
}
