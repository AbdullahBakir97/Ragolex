<script setup lang="ts">
import { BookOpenText, Check, GraduationCap, LoaderCircle, RotateCcw, X } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { RouterLink } from "vue-router";

import { ApiError, api } from "@/api/client";
import type { StudyKind, StudyMaterial, StudySource } from "@/api/types";
import ChunkDrawer from "@/components/ChunkDrawer.vue";
import { useProject } from "@/composables/useProject";
import { formatCost, formatNumber } from "@/lib/format";

const { name, files } = useProject();

const KINDS: { kind: StudyKind; label: string; help: string }[] = [
  { kind: "summary", label: "Summary", help: "Key points, in the document's order" },
  { kind: "flashcards", label: "Flashcards", help: "A question on the front, its answer on the back" },
  { kind: "quiz", label: "Quiz", help: "Multiple choice, with why each answer is right" },
];
const COUNTS = [5, 10, 15, 20];

const fileId = ref("");
const kind = ref<StudyKind>("flashcards");
const count = ref(10);
const material = ref<StudyMaterial | null>(null);
const loading = ref(false);
const error = ref<string | null>(null);
const notProcessed = ref(false);

// The first document, once the project's files are known.
watch(
  files,
  (list) => {
    if (!list.some((file) => file.file_id === fileId.value)) fileId.value = list[0]?.file_id ?? "";
  },
  { immediate: true },
);

async function generate() {
  if (!fileId.value || loading.value) return;
  loading.value = true;
  error.value = null;
  notProcessed.value = false;
  try {
    material.value = await api.study(name.value, fileId.value, kind.value, count.value);
    flipped.value = new Set();
    chosen.value = {};
  } catch (caught) {
    notProcessed.value = caught instanceof ApiError && caught.signal === "file_not_processed";
    error.value = caught instanceof ApiError ? caught.message : "The study material could not be written.";
  } finally {
    loading.value = false;
  }
}

const title = computed(() => KINDS.find((entry) => entry.kind === material.value?.kind)?.label ?? "");
const sources = computed(() => new Map((material.value?.sources ?? []).map((source) => [source.number, source])));

function cited(numbers: number[]): StudySource[] {
  return numbers.map((number) => sources.value.get(number)).filter((source): source is StudySource => !!source);
}

function where(source: StudySource): string {
  if (source.page !== null) return `p. ${source.page}`;
  if (source.section) return source.section;
  return `Passage ${source.number}`;
}

// The passage open in the drawer.
const opened = ref<StudySource | null>(null);

// Flashcards turned over to their answer.
const flipped = ref(new Set<number>());
function flip(index: number) {
  const next = new Set(flipped.value);
  if (!next.delete(index)) next.add(index);
  flipped.value = next;
}
const allFlipped = computed(() => material.value?.kind === "flashcards" && flipped.value.size === material.value.items.length);
function flipAll() {
  flipped.value = allFlipped.value ? new Set() : new Set(material.value?.items.map((_, index) => index));
}

// The choice made for each quiz question, by its position.
const chosen = ref<Record<number, number>>({});
const score = computed(() => {
  if (material.value?.kind !== "quiz") return null;
  const items = material.value.items;
  const answered = Object.keys(chosen.value).length;
  const right = items.filter((item, index) => chosen.value[index] === item.answer).length;
  return { answered, right, total: items.length };
});
function choose(question: number, choice: number) {
  if (chosen.value[question] === undefined) chosen.value = { ...chosen.value, [question]: choice };
}
</script>

<template>
  <section class="study">
    <div>
      <h2>Study</h2>
      <p class="muted small">Turn a document into a summary, flashcards or a quiz. Every item links to the passage it comes from.</p>
    </div>

    <div v-if="!files.length" class="empty card">
      <BookOpenText :size="22" class="subtle" />
      <p>Upload and process a document first, on the <RouterLink :to="{ name: 'documents', params: { project: name } }">Documents</RouterLink> page.</p>
    </div>

    <form v-else class="controls card" @submit.prevent="generate">
      <label class="field document">
        <span>Document</span>
        <select v-model="fileId" class="select" required>
          <option v-for="file in files" :key="file.file_id" :value="file.file_id">{{ file.original_name }}</option>
        </select>
      </label>
      <fieldset class="field">
        <legend>Write</legend>
        <div class="kinds">
          <label v-for="entry in KINDS" :key="entry.kind" class="kind" :class="{ active: kind === entry.kind }" :title="entry.help">
            <input v-model="kind" type="radio" name="study-kind" :value="entry.kind" class="visually-hidden" />
            {{ entry.label }}
          </label>
        </div>
      </fieldset>
      <label class="field count">
        <span>At most</span>
        <select v-model.number="count" class="select">
          <option v-for="option in COUNTS" :key="option" :value="option">{{ option }} {{ kind === "summary" ? "points" : kind === "quiz" ? "questions" : "cards" }}</option>
        </select>
      </label>
      <button type="submit" class="btn btn-primary" :disabled="loading || !fileId">
        <LoaderCircle v-if="loading" :size="16" class="spin" />
        <GraduationCap v-else :size="16" />
        {{ loading ? "Writing…" : "Write" }}
      </button>
    </form>

    <div v-if="error" class="alert alert-danger" role="alert">
      <span>
        {{ error }}
        <template v-if="notProcessed">
          Process it on the <RouterLink :to="{ name: 'documents', params: { project: name } }">Documents</RouterLink> page.
        </template>
      </span>
    </div>

    <div v-if="loading && !material" class="skeleton result-skeleton" />

    <article v-if="material" class="result" :aria-busy="loading">
      <header class="result-head">
        <div>
          <h3>{{ title }} of {{ material.original_name }}</h3>
          <p class="subtle small">
            {{ formatNumber(material.items.length) }} {{ material.items.length === 1 ? "item" : "items" }}
            · {{ formatNumber((material.usage.input_tokens ?? 0) + (material.usage.output_tokens ?? 0)) }} tokens
            <template v-if="material.usage.cost_usd !== null"> · {{ formatCost(material.usage.cost_usd) }}</template>
            · <span class="mono">{{ material.prompt_version }}</span>
          </p>
        </div>
        <button v-if="material.kind === 'flashcards' && material.items.length" type="button" class="btn btn-sm" @click="flipAll">
          {{ allFlipped ? "Hide the answers" : "Show all answers" }}
        </button>
        <p v-if="score" class="score" aria-live="polite">
          <strong>{{ score.right }}</strong> right of {{ score.answered }} answered
          <span class="subtle">({{ score.total }} questions)</span>
          <button v-if="score.answered" type="button" class="btn btn-ghost btn-sm" @click="chosen = {}">
            <RotateCcw :size="14" /> Start over
          </button>
        </p>
      </header>

      <p v-if="material.passages < material.chunks" class="alert small">
        The document is long: {{ formatNumber(material.passages) }} of its {{ formatNumber(material.chunks) }} passages, spread over it, were used.
      </p>
      <p v-if="!material.items.length" class="alert alert-warning">The model wrote nothing usable from this document. Try again, or another kind.</p>

      <ol v-if="material.kind === 'summary'" class="points">
        <li v-for="(point, index) in material.items" :key="index">
          <span>{{ point.text }}</span>
          <span class="cites">
            <button v-for="source in cited(point.sources)" :key="source.number" type="button" class="cite" @click="opened = source">{{ where(source) }}</button>
          </span>
        </li>
      </ol>

      <ul v-else-if="material.kind === 'flashcards'" class="cards">
        <li v-for="(card, index) in material.items" :key="index" class="flashcard card" :class="{ flipped: flipped.has(index) }">
          <button type="button" class="face" :aria-expanded="flipped.has(index)" @click="flip(index)">
            <span class="side subtle small">{{ flipped.has(index) ? "Answer" : "Question" }} {{ index + 1 }}</span>
            <span class="front">{{ card.front }}</span>
            <span v-if="flipped.has(index)" class="back">{{ card.back }}</span>
            <span v-else class="hint subtle small">Show the answer</span>
          </button>
          <span v-if="flipped.has(index)" class="cites">
            <button v-for="source in cited(card.sources)" :key="source.number" type="button" class="cite" @click="opened = source">{{ where(source) }}</button>
          </span>
        </li>
      </ul>

      <ol v-else class="quiz">
        <li v-for="(question, index) in material.items" :key="index" class="question card">
          <fieldset>
            <legend>{{ question.question }}</legend>
            <div class="choices">
              <button
                v-for="(choice, position) in question.choices"
                :key="position"
                type="button"
                class="choice"
                :class="{
                  right: chosen[index] !== undefined && position === question.answer,
                  wrong: chosen[index] === position && position !== question.answer,
                }"
                :aria-pressed="chosen[index] === position"
                :disabled="chosen[index] !== undefined"
                @click="choose(index, position)"
              >
                <span class="letter" aria-hidden="true">{{ "ABCD"[position] }}</span>
                <span>{{ choice }}</span>
                <Check v-if="chosen[index] !== undefined && position === question.answer" :size="16" class="mark" aria-label="right answer" />
                <X v-else-if="chosen[index] === position" :size="16" class="mark" aria-label="wrong answer" />
              </button>
            </div>
          </fieldset>
          <div v-if="chosen[index] !== undefined" class="explanation small">
            <strong>{{ chosen[index] === question.answer ? "Right." : "Not quite." }}</strong>
            {{ question.explanation }}
            <span class="cites">
              <button v-for="source in cited(question.sources)" :key="source.number" type="button" class="cite" @click="opened = source">{{ where(source) }}</button>
            </span>
          </div>
        </li>
      </ol>
    </article>

    <ChunkDrawer
      :project="name"
      :file="opened && material ? { file_id: material.file_id, original_name: material.original_name } : null"
      :focus-chunk="opened?.chunk_index ?? null"
      @close="opened = null"
    />
  </section>
</template>

<style scoped>
.study {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.empty {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 18px;
}

.controls {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 12px;
  padding: 14px 16px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 0;
  padding: 0;
  border: 0;
  font-size: 12.5px;
  font-weight: 550;
  color: var(--text-2);
}

.field legend {
  margin-bottom: 4px;
  padding: 0;
}

.document {
  flex: 1 1 220px;
  min-width: 0;
}

.count .select {
  width: auto;
}

.kinds {
  display: inline-flex;
  overflow: hidden;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
}

.kind {
  display: flex;
  align-items: center;
  min-height: 32px;
  padding: 0 12px;
  background: var(--surface);
  color: var(--text-2);
  font-size: 13.5px;
  font-weight: 500;
  cursor: pointer;
}

.kind + .kind {
  border-left: 1px solid var(--border-strong);
}

.kind.active {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
}

.kind:focus-within {
  box-shadow: var(--focus);
}

.result-skeleton {
  height: 220px;
  border-radius: var(--radius);
}

.result {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.result-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.score {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
}

.points {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 0;
  padding-left: 22px;
  line-height: 1.55;
}

.points li::marker {
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}

.cites {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-left: 6px;
  vertical-align: baseline;
}

.cite {
  padding: 1px 7px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface-2);
  color: var(--text-2);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.cite:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.cite:focus-visible,
.face:focus-visible,
.choice:focus-visible {
  box-shadow: var(--focus);
  outline: none;
}

.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.flashcard {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 0 0 12px;
  transition: border-color 0.15s;
}

.flashcard.flipped {
  border-color: var(--accent);
}

.flashcard .cites {
  margin: 0 14px;
}

.face {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 120px;
  padding: 14px 14px 0;
  border: 0;
  border-radius: var(--radius);
  background: none;
  color: var(--text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.front {
  font-weight: 600;
  line-height: 1.45;
}

.back {
  color: var(--text-2);
  line-height: 1.5;
}

.hint {
  margin-top: auto;
}

.quiz {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.question {
  padding: 14px 16px;
}

.question fieldset {
  margin: 0;
  padding: 0;
  border: 0;
}

.question legend {
  margin-bottom: 10px;
  padding: 0;
  font-weight: 600;
  line-height: 1.45;
}

.choices {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 8px;
}

.choice {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.choice:hover:not(:disabled) {
  border-color: var(--accent);
}

.choice:disabled {
  cursor: default;
}

.choice.right {
  border-color: var(--success);
  background: var(--success-soft);
}

.choice.wrong {
  border-color: var(--danger);
  background: var(--danger-soft);
}

.letter {
  display: grid;
  flex: none;
  width: 22px;
  height: 22px;
  place-items: center;
  border-radius: 50%;
  background: var(--surface-2);
  color: var(--text-2);
  font-size: 12px;
  font-weight: 600;
}

.mark {
  flex: none;
  margin-left: auto;
}

.right .mark {
  color: var(--success);
}

.wrong .mark {
  color: var(--danger);
}

.explanation {
  margin-top: 10px;
  color: var(--text-2);
  line-height: 1.5;
}
</style>
