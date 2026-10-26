<script setup lang="ts">
import {
  ArrowUp,
  Check,
  CircleHelp,
  Copy,
  Files,
  History,
  MessageSquareText,
  RotateCcw,
  Search,
  SlidersHorizontal,
  Square,
  SquarePen,
  ThumbsDown,
  ThumbsUp,
  TriangleAlert,
} from "@lucide/vue";
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { ApiError } from "@/api/client";
import type { Citation, Rating } from "@/api/types";
import AnswerText from "@/components/AnswerText.vue";
import ChunkDrawer from "@/components/ChunkDrawer.vue";
import ConversationList from "@/components/ConversationList.vue";
import FilePicker from "@/components/FilePicker.vue";
import SourceCard from "@/components/SourceCard.vue";
import { type AskSettings, type Turn, useAsk } from "@/composables/useAsk";
import { rememberConversation, useConversations } from "@/composables/useConversations";
import { useProject } from "@/composables/useProject";
import { useToasts } from "@/composables/useToasts";
import { formatCost, formatNumber } from "@/lib/format";

const { name, project, loading: projectLoading, fileName, files, tags } = useProject();
const tagOptions = computed(() => tags.value.map((t) => ({ file_id: t.tag, original_name: `${t.tag} (${t.files})` })));
const route = useRoute();
const router = useRouter();
const toasts = useToasts();

const conversationId = computed(() =>
  typeof route.params.conversation === "string" && route.params.conversation ? route.params.conversation : null,
);
const conversations = useConversations(name);

function show(id: string | null) {
  showHistory.value = false;
  const params = id ? { project: name.value, conversation: id } : { project: name.value };
  return router.push({ name: "ask", params });
}

const settings = ref<AskSettings>({ top_k: 5, min_score: null, stream: true, research: false, files: [], tags: [] });
const chosenFiles = computed({
  get: () => settings.value.files ?? [],
  set: (value: string[]) => (settings.value.files = value),
});
const chosenTags = computed({
  get: () => settings.value.tags ?? [],
  set: (value: string[]) => (settings.value.tags = value),
});
const narrowedLabel = computed(() => {
  const parts = [];
  if (chosenFiles.value.length)
    parts.push(chosenFiles.value.length === 1 ? "1 document" : `${chosenFiles.value.length} documents`);
  if (chosenTags.value.length)
    parts.push(chosenTags.value.length === 1 ? `#${chosenTags.value[0]}` : `${chosenTags.value.length} tags`);
  return parts.join(" · ");
});
const { turns, busy, loading, ask, stop, retry, rate } = useAsk(name, conversationId, settings, {
  // The new conversation gets its own address, without a new history entry.
  onStarted: (id) => {
    void router.replace({ name: "ask", params: { project: name.value, conversation: id } });
    void conversations.refresh();
  },
  onAnswered: () => void conversations.refresh(),
  onLoadFailed: (error, missing) => {
    toasts.error("The conversation could not be opened", error.message);
    if (missing) void router.replace({ name: "ask", params: { project: name.value } });
  },
});

watch(conversationId, (id) => rememberConversation(name.value, id), { immediate: true });

const showHistory = ref(false);

// Escape closes the conversations drawer of narrow screens.
function onKey(event: KeyboardEvent) {
  if (event.key === "Escape") showHistory.value = false;
}
watch(showHistory, (open) =>
  open ? window.addEventListener("keydown", onKey) : window.removeEventListener("keydown", onKey),
);
onBeforeUnmount(() => window.removeEventListener("keydown", onKey));
const conversationTitle = computed(
  () => conversations.items.value.find((item) => item.id === conversationId.value)?.title ?? null,
);

async function removeConversation(id: string) {
  try {
    await conversations.remove(id);
    toasts.success("Conversation deleted");
    if (id === conversationId.value) await router.replace({ name: "ask", params: { project: name.value } });
  } catch (caught) {
    toasts.error("The conversation could not be deleted", caught instanceof ApiError ? caught.message : undefined);
    void conversations.refresh();
  }
}

const question = ref("");
const showSettings = ref(false);
const input = ref<HTMLTextAreaElement | null>(null);
const active = ref<{ turn: number; number: number } | null>(null);
const opened = ref<{ file: { file_id: string; original_name: string }; chunk: number } | null>(null);
const copied = ref<number | null>(null);

const ready = computed(() => !!project.value && project.value.embedded_chunks_count > 0);
const canAsk = computed(() => ready.value || turns.value.length > 0);
const minScoreText = computed({
  get: () => (settings.value.min_score === null ? "" : String(settings.value.min_score)),
  set: (value: string) => {
    const number = Number(value);
    settings.value.min_score = value.trim() === "" || Number.isNaN(number) ? null : Math.max(-1, Math.min(1, number));
  },
});

const examples = [
  "Summarize the main points of these documents.",
  "What are the key definitions?",
  "Which steps or recommendations are given?",
];

function submit() {
  const text = question.value.trim();
  if (!text || busy.value) return;
  question.value = "";
  resize();
  void ask(text);
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    submit();
  }
}

function resize() {
  void nextTick(() => {
    const el = input.value;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  });
}

function useExample(text: string) {
  question.value = text;
  resize();
  input.value?.focus();
}

function newConversation() {
  void show(null).then(() => input.value?.focus());
}

function scrollToSource(turn: Turn, number: number) {
  active.value = { turn: turn.id, number };
  document.getElementById(`source-${turn.id}-${number}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function open(citation: Citation) {
  opened.value = {
    file: { file_id: citation.file_id, original_name: fileName(citation.file_id) },
    chunk: citation.chunk_index,
  };
}

async function copy(turn: Turn) {
  try {
    await navigator.clipboard.writeText(turn.text);
    copied.value = turn.id;
    setTimeout(() => (copied.value = null), 1500);
  } catch {
    // Clipboard access can be denied; the text stays selectable.
  }
}

// The answer whose thumbs down is waiting for an optional comment.
const commenting = ref<number | null>(null);
const comment = ref("");

async function setRating(turn: Turn, rating: Rating | null, note?: string) {
  try {
    await rate(turn, rating, note);
  } catch (caught) {
    toasts.error("The rating could not be saved", caught instanceof ApiError ? caught.message : undefined);
  }
}

function thumbsUp(turn: Turn) {
  commenting.value = null;
  void setRating(turn, turn.feedback?.rating === "up" ? null : "up");
}

function thumbsDown(turn: Turn) {
  if (turn.feedback?.rating === "down") {
    commenting.value = null;
    void setRating(turn, null);
    return;
  }
  void setRating(turn, "down");
  comment.value = "";
  commenting.value = turn.id;
}

function saveComment(turn: Turn) {
  const note = comment.value.trim();
  commenting.value = null;
  if (note) void setRating(turn, "down", note);
}

function tokens(turn: Turn) {
  const usage = turn.answer?.usage;
  if (turn.stored) return null;
  if (!usage || usage.input_tokens === null) return null;
  if (usage.input_tokens === 0 && usage.output_tokens === 0) return "Model not called";
  return `${formatNumber(usage.input_tokens)} in · ${formatNumber(usage.output_tokens ?? 0)} out`;
}

// Follow the newest answer while it is written, unless the reader scrolled up.
watch(
  () => turns.value.at(-1)?.text.length,
  () => {
    const atBottom = window.innerHeight + window.scrollY >= document.body.scrollHeight - 160;
    if (atBottom) void nextTick(() => window.scrollTo({ top: document.body.scrollHeight }));
  },
);
watch(
  () => turns.value.length,
  () => void nextTick(() => window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" })),
);
</script>

<template>
  <div class="ask-layout">
    <div v-if="showHistory" class="history-overlay" @click="showHistory = false" />
    <aside class="history" :class="{ open: showHistory }">
      <ConversationList
        :items="conversations.items.value"
        :total="conversations.total.value"
        :loading="conversations.loading.value"
        :error="conversations.error.value?.message ?? null"
        :active="conversationId"
        @select="show"
        @create="newConversation"
        @remove="removeConversation"
        @more="conversations.more"
        @retry="conversations.refresh"
        @close="showHistory = false"
      />
    </aside>

  <section class="ask">
    <div class="toolbar">
      <button class="btn btn-ghost btn-sm" :aria-expanded="showHistory" @click="showHistory = true">
        <History :size="15" /> Conversations
      </button>
      <span class="toolbar-title subtle small">{{ conversationTitle ?? "" }}</span>
      <button v-if="conversationId" class="btn btn-ghost btn-sm" @click="newConversation">
        <SquarePen :size="14" /> New
      </button>
    </div>

    <div v-if="loading" class="thread-loading" aria-label="Loading the conversation">
      <div v-for="i in 2" :key="i" class="skeleton turn-skeleton" />
    </div>

    <div v-else-if="!projectLoading && !ready && !turns.length" class="empty card">
      <span class="empty-icon"><Files :size="24" /></span>
      <h2>{{ project ? "Nothing is indexed yet" : "Add documents first" }}</h2>
      <p class="muted">
        {{
          project
            ? "Answers come from indexed chunks. Index the project from the banner above."
            : "Questions are answered from this project's documents. Upload a document to begin."
        }}
      </p>
      <RouterLink v-if="!project" :to="{ name: 'documents', params: { project: name } }" class="btn btn-primary">
        Upload documents
      </RouterLink>
    </div>

    <div v-else-if="!turns.length" class="intro">
      <span class="empty-icon"><MessageSquareText :size="24" /></span>
      <h2>Ask about {{ name }}</h2>
      <p class="muted">
        Answers come only from this project's documents, with numbered sources you can open. Ask follow-up
        questions: each conversation is kept.
      </p>
      <div class="examples">
        <button v-for="example in examples" :key="example" class="example" @click="useExample(example)">
          {{ example }}
        </button>
      </div>
    </div>

    <ol v-else class="thread">
      <li v-for="turn in turns" :key="turn.id" class="turn">
        <div class="question">
          <p>{{ turn.question }}</p>
        </div>

        <div class="answer card">
          <p v-if="turn.answer?.search_question" class="searched subtle small">
            <Search :size="13" />
            <span>Searched for <q>{{ turn.answer.search_question }}</q></span>
          </p>
          <details v-if="turn.answer?.research?.length" class="research subtle small">
            <summary>
              <Search :size="13" />
              <span>Researched with {{ turn.answer.research.length }} {{ turn.answer.research.length === 1 ? "search" : "searches" }}</span>
            </summary>
            <ol>
              <li v-for="(step, index) in turn.answer.research" :key="index">
                <q>{{ step.query }}</q>
                <span class="found">{{ step.results }} found</span>
              </li>
            </ol>
          </details>

          <div v-if="turn.status === 'failed'" class="alert alert-danger">
            <TriangleAlert :size="18" />
            <span class="grow">{{ turn.error }}</span>
            <button class="btn btn-sm" @click="retry(turn)"><RotateCcw :size="14" /> Retry</button>
          </div>

          <div v-else-if="turn.status === 'done' && turn.answer?.signal === 'no_answer'" class="no-answer">
            <CircleHelp :size="20" />
            <div>
              <h3>The documents don't answer this</h3>
              <p class="muted small">
                No indexed passage was close enough to the question. Try rephrasing it, or lower the minimum score.
              </p>
            </div>
          </div>

          <template v-else>
            <div v-if="turn.status === 'streaming' && !turn.text" class="thinking" aria-label="Writing the answer">
              <span /><span /><span />
              <span class="muted small label">Reading the sources…</span>
            </div>
            <AnswerText
              v-else
              :text="turn.text"
              :streaming="turn.status === 'streaming'"
              :cited="turn.answer?.citations.map((c) => c.number)"
              :active="active?.turn === turn.id ? active.number : null"
              @cite="(n) => scrollToSource(turn, n)"
              @hover="(n) => (active = n === null ? null : { turn: turn.id, number: n })"
            />
            <p v-if="turn.status === 'stopped'" class="subtle small stopped">Stopped.</p>
          </template>

          <div v-if="turn.answer?.citations.length" class="sources">
            <h4 class="sources-title">Sources</h4>
            <SourceCard
              v-for="citation in turn.answer.citations"
              :id="`source-${turn.id}-${citation.number}`"
              :key="citation.number"
              :number="citation.number"
              :file-id="citation.file_id"
              :file-name="fileName(citation.file_id)"
              :chunk-index="citation.chunk_index"
              :page="citation.page"
              :section="citation.section"
              :score="citation.score"
              :text="citation.text"
              :active="active?.turn === turn.id && active.number === citation.number"
              @open="open(citation)"
            />
          </div>

          <footer v-if="turn.status === 'done' && turn.answer" class="meta">
            <span v-if="tokens(turn)" class="meta-item" title="Tokens">{{ tokens(turn) }}</span>
            <span v-if="!turn.stored" class="meta-item" title="Cost">{{ formatCost(turn.answer.usage.cost_usd) }}</span>
            <span v-if="turn.seconds !== null" class="meta-item">{{ turn.seconds.toFixed(1) }} s</span>
            <span class="meta-item mono" title="Prompt version">{{ turn.answer.prompt_version }}</span>
            <span class="grow" />
            <template v-if="turn.answer.message_id != null">
              <button
                class="btn btn-ghost btn-icon btn-sm rating"
                :class="{ on: turn.feedback?.rating === 'up' }"
                :aria-pressed="turn.feedback?.rating === 'up'"
                title="Good answer"
                aria-label="Good answer"
                @click="thumbsUp(turn)"
              >
                <ThumbsUp :size="14" />
              </button>
              <button
                class="btn btn-ghost btn-icon btn-sm rating"
                :class="{ on: turn.feedback?.rating === 'down' }"
                :aria-pressed="turn.feedback?.rating === 'down'"
                title="Bad answer"
                aria-label="Bad answer"
                @click="thumbsDown(turn)"
              >
                <ThumbsDown :size="14" />
              </button>
            </template>
            <button
              v-if="turn.text"
              class="btn btn-ghost btn-sm"
              :aria-label="copied === turn.id ? 'Copied' : 'Copy answer'"
              @click="copy(turn)"
            >
              <Check v-if="copied === turn.id" :size="14" />
              <Copy v-else :size="14" />
              {{ copied === turn.id ? "Copied" : "Copy" }}
            </button>
          </footer>
          <form v-if="commenting === turn.id" class="comment" @submit.prevent="saveComment(turn)">
            <label class="small muted" :for="`comment-${turn.id}`">What was wrong? (optional)</label>
            <div class="comment-row">
              <input
                :id="`comment-${turn.id}`"
                v-model="comment"
                class="input"
                maxlength="1000"
                placeholder="For example: it missed the Friday rule"
                @keydown.escape="commenting = null"
              />
              <button type="submit" class="btn btn-sm" :disabled="!comment.trim()">Send</button>
              <button type="button" class="btn btn-ghost btn-sm" @click="commenting = null">Skip</button>
            </div>
          </form>
        </div>
      </li>
    </ol>

    <div class="composer-wrap">
      <div v-if="showSettings" class="settings card">
        <label class="field">
          <span>Sources (top k)</span>
          <input v-model.number="settings.top_k" class="input" type="number" min="1" max="20" />
        </label>
        <label class="field">
          <span>Minimum score</span>
          <input v-model.lazy="minScoreText" class="input" type="number" min="-1" max="1" step="0.05" placeholder="Server default" />
        </label>
        <label class="toggle">
          <input v-model="settings.stream" type="checkbox" />
          <span>Stream the answer as it is written</span>
        </label>
        <label class="toggle research-toggle">
          <input v-model="settings.research" type="checkbox" />
          <span>
            Research mode
            <span class="subtle">· plans several searches, for questions with several parts; slower</span>
          </span>
        </label>
        <div class="field documents">
          <span>Answer from</span>
          <div class="pickers">
            <FilePicker v-model="chosenFiles" :files="files" />
            <FilePicker v-if="tags.length" v-model="chosenTags" :files="tagOptions" tags />
          </div>
        </div>
      </div>

      <form class="composer card" @submit.prevent="submit">
        <textarea
          ref="input"
          v-model="question"
          class="composer-input"
          rows="1"
          maxlength="2000"
          :placeholder="
            !canAsk
              ? 'Upload and index documents to ask questions'
              : turns.length
                ? 'Ask a follow-up question…'
                : `Ask a question about ${name}…`
          "
          :disabled="!canAsk || loading"
          aria-label="Question"
          @input="resize"
          @keydown="onKeydown"
        />
        <div class="composer-actions">
          <button
            type="button"
            class="btn btn-ghost btn-icon btn-sm"
            :class="{ on: showSettings }"
            title="Answer settings"
            aria-label="Answer settings"
            :aria-expanded="showSettings"
            @click="showSettings = !showSettings"
          >
            <SlidersHorizontal :size="16" />
          </button>
          <button
            v-if="turns.length && !busy"
            type="button"
            class="btn btn-ghost btn-icon btn-sm"
            title="New conversation"
            aria-label="New conversation"
            @click="newConversation"
          >
            <SquarePen :size="16" />
          </button>
          <button
            v-if="narrowedLabel && !showSettings"
            type="button"
            class="badge narrowed"
            title="Answers use only the chosen documents"
            @click="showSettings = true"
          >
            {{ narrowedLabel }}
          </button>
          <span class="grow" />
          <span class="hint subtle small">Enter to send · Shift+Enter for a new line</span>
          <button v-if="busy" type="button" class="btn btn-sm send" aria-label="Stop" @click="stop">
            <Square :size="12" fill="currentColor" /> Stop
          </button>
          <button v-else type="submit" class="btn btn-primary btn-icon btn-sm send" aria-label="Ask" :disabled="!question.trim()">
            <ArrowUp :size="16" />
          </button>
        </div>
      </form>
    </div>

    <ChunkDrawer
      :project="name"
      :file="opened?.file ?? null"
      :focus-chunk="opened?.chunk ?? null"
      @close="opened = null"
    />
  </section>
  </div>
</template>

<style scoped>
.ask-layout {
  display: flex;
  flex: 1;
  gap: 28px;
  width: 100%;
}

.history {
  position: sticky;
  top: 132px;
  flex: none;
  align-self: flex-start;
  width: 240px;
  max-height: calc(100vh - 152px);
  overflow-y: auto;
}

.history-overlay {
  display: none;
}

.ask {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 18px;
  min-width: 0;
  max-width: 820px;
  margin: 0 auto;
}

.toolbar {
  display: none;
  align-items: center;
  gap: 8px;
  margin: -6px 0 -4px;
}

.toolbar-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Narrower screens keep the conversations in a drawer. */
@media (max-width: 1179px) {
  .toolbar {
    display: flex;
  }

  .history {
    position: fixed;
    top: 0;
    bottom: 0;
    left: 0;
    z-index: 60;
    /* Stretched between top and bottom, which flex-start would undo. */
    align-self: auto;
    width: min(300px, 86vw);
    max-height: none;
    padding: 16px;
    background: var(--surface);
    box-shadow: var(--shadow-lg);
    transform: translateX(-105%);
    visibility: hidden;
    transition:
      transform 0.2s ease,
      visibility 0.2s;
  }

  .history.open {
    transform: none;
    visibility: visible;
  }

  .history-overlay {
    position: fixed;
    inset: 0;
    z-index: 59;
    display: block;
    background: rgb(0 0 0 / 35%);
  }
}

.thread-loading {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.turn-skeleton {
  height: 150px;
}

.rating.on {
  background: var(--accent-soft);
  color: var(--accent-text);
}

.comment {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: -4px;
}

.comment-row {
  display: flex;
  gap: 6px;
}

.comment-row .input {
  flex: 1;
  min-width: 0;
}

.searched {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-bottom: -4px;
}

.searched svg {
  flex: none;
  margin-top: 3px;
}

.searched q {
  color: var(--text-2);
}

.research {
  margin-bottom: -4px;
}

.research summary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}

.research ol {
  display: grid;
  gap: 4px;
  margin: 6px 0 0;
  padding-left: 38px;
}

.research q {
  color: var(--text-2);
  overflow-wrap: anywhere;
}

.research .found {
  margin-left: 6px;
  white-space: nowrap;
}

.empty,
.intro {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  margin: auto 0;
  padding: 36px 24px;
  text-align: center;
}

.intro {
  padding-bottom: 12px;
}

.empty-icon {
  display: grid;
  place-items: center;
  width: 52px;
  height: 52px;
  margin-bottom: 6px;
  border-radius: 14px;
  background: var(--accent-soft);
  color: var(--accent-text);
}

.empty .btn {
  margin-top: 10px;
}

.examples {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
  margin-top: 14px;
}

.example {
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface);
  color: var(--text-2);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
  transition:
    border-color 0.15s,
    color 0.15s;
}

.example:hover {
  border-color: var(--accent);
  color: var(--text);
}

.thread {
  display: flex;
  flex-direction: column;
  gap: 22px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.turn {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.question {
  align-self: flex-end;
  max-width: 85%;
  padding: 10px 14px;
  border-radius: 14px 14px 4px 14px;
  background: var(--bubble);
  color: var(--on-bubble);
  font-size: 14.5px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.answer {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px 18px;
}

.no-answer {
  display: flex;
  gap: 12px;
  color: var(--warning);
}

.no-answer h3 {
  color: var(--text);
}

.thinking {
  display: flex;
  align-items: center;
  gap: 5px;
  height: 24px;
}

.thinking span:not(.label) {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent);
  animation: pulse 1.2s ease-in-out infinite;
}

.thinking span:nth-child(2) {
  animation-delay: 0.15s;
}

.thinking span:nth-child(3) {
  animation-delay: 0.3s;
}

.thinking .label {
  margin-left: 8px;
}

@keyframes pulse {
  0%,
  80%,
  100% {
    opacity: 0.25;
    transform: scale(0.8);
  }
  40% {
    opacity: 1;
    transform: scale(1);
  }
}

.stopped {
  margin-top: -6px;
}

.sources {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.sources-title {
  color: var(--text-3);
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 14px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
  color: var(--text-3);
  font-size: 12.5px;
}

.grow {
  flex: 1;
}

.composer-wrap {
  position: sticky;
  bottom: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: auto;
  padding: 12px 0 16px;
  background: linear-gradient(to bottom, transparent, var(--bg) 22%);
}

.composer {
  padding: 10px 12px 8px;
  box-shadow: var(--shadow);
}

.composer:focus-within {
  border-color: var(--accent);
  box-shadow: var(--focus), var(--shadow);
}

.composer-input {
  display: block;
  width: 100%;
  min-height: 24px;
  max-height: 200px;
  padding: 4px 2px;
  border: 0;
  background: transparent;
  color: var(--text);
  font: inherit;
  font-size: 15px;
  resize: none;
  outline: none;
  box-shadow: none;
}

.composer-input:disabled {
  cursor: not-allowed;
}

.composer-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 6px;
}

.on {
  background: var(--accent-soft);
  color: var(--accent-text);
}

.hint {
  margin-right: 8px;
}

@media (max-width: 640px) {
  .hint {
    display: none;
  }
}

.send {
  border-radius: 8px;
}

.settings {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 160px)) 1fr;
  align-items: end;
  gap: 14px;
  padding: 14px 16px;
  box-shadow: var(--shadow);
}

@media (max-width: 640px) {
  .settings {
    grid-template-columns: 1fr 1fr;
  }

  .toggle {
    grid-column: 1 / -1;
  }
}

.documents,
.research-toggle {
  grid-column: 1 / -1;
}

.research-toggle {
  height: auto;
  min-height: 34px;
}

.pickers {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.narrowed {
  border: 0;
  background: var(--accent-soft);
  color: var(--accent-text);
  font: inherit;
  font-size: 12px;
  font-weight: 550;
  cursor: pointer;
}

.toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 34px;
  color: var(--text-2);
  cursor: pointer;
}

.toggle input {
  flex: none;
  width: 16px;
  height: 16px;
  accent-color: var(--accent);
}
</style>
