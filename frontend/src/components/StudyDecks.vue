<script setup lang="ts">
import { Download, Layers, PartyPopper, Play, Trash2, X } from "@lucide/vue";
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";

import { ApiError, api } from "@/api/client";
import type { Deck, ReviewCard, ReviewGrade } from "@/api/types";
import { useToasts } from "@/composables/useToasts";
import { formatNumber } from "@/lib/format";

// The project's decks of flashcards, and reviewing one by spaced repetition.
const props = defineProps<{ project: string }>();

const toasts = useToasts();
const decks = ref<Deck[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);

async function refresh() {
  try {
    decks.value = await api.decks(props.project);
    error.value = null;
  } catch (caught) {
    // A project without files is not known to the server yet: it has no decks.
    const empty = caught instanceof ApiError && caught.signal === "project_not_found";
    decks.value = [];
    error.value = empty ? null : caught instanceof ApiError ? caught.message : "The decks could not be loaded.";
  } finally {
    loading.value = false;
  }
}
defineExpose({ refresh });

watch(() => props.project, refresh);
onMounted(refresh);

async function exportDeck(deck: Deck) {
  try {
    const { blob, filename } = await api.ankiExport(props.project, deck.id);
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = filename ?? `${deck.name}.txt`;
    link.click();
    URL.revokeObjectURL(link.href);
  } catch (caught) {
    toasts.error("The deck could not be exported", caught instanceof ApiError ? caught.message : undefined);
  }
}

async function remove(deck: Deck) {
  if (!window.confirm(`Delete the deck “${deck.name}” and its ${deck.cards} cards? Their review history goes with them.`)) return;
  try {
    await api.deleteDeck(props.project, deck.id);
    decks.value = decks.value.filter((other) => other.id !== deck.id);
    toasts.success("Deck deleted", `“${deck.name}” and its cards are gone.`);
  } catch (caught) {
    toasts.error("The deck could not be deleted", caught instanceof ApiError ? caught.message : undefined);
  }
}

// Reviewing: the deck, its due cards, and the one shown.
const reviewing = ref<Deck | null>(null);
const queue = ref<ReviewCard[]>([]);
const position = ref(0);
const revealed = ref(false);
const grading = ref(false);
const reviewed = ref(0);
const card = computed(() => queue.value[position.value] ?? null);
const reviewPanel = ref<HTMLElement | null>(null);

const GRADES: { grade: ReviewGrade; label: string; key: string }[] = [
  { grade: "again", label: "Again", key: "1" },
  { grade: "hard", label: "Hard", key: "2" },
  { grade: "good", label: "Good", key: "3" },
  { grade: "easy", label: "Easy", key: "4" },
];

async function startReview(deck: Deck) {
  try {
    const due = await api.reviewQueue(props.project, deck.id);
    reviewing.value = due.deck;
    queue.value = due.cards;
    position.value = 0;
    revealed.value = false;
    reviewed.value = 0;
    requestAnimationFrame(() => reviewPanel.value?.focus());
  } catch (caught) {
    toasts.error("The cards could not be loaded", caught instanceof ApiError ? caught.message : undefined);
  }
}

async function grade(value: ReviewGrade) {
  if (!reviewing.value || !card.value || grading.value || !revealed.value) return;
  grading.value = true;
  try {
    await api.reviewCard(props.project, reviewing.value.id, card.value.id, value);
    reviewed.value += 1;
    position.value += 1;
    revealed.value = false;
    // Forgotten cards come back in minutes: fetch them once the queue is done.
    if (position.value >= queue.value.length) {
      const due = await api.reviewQueue(props.project, reviewing.value.id);
      queue.value = due.cards.filter((next) => new Date(next.due_at).getTime() <= Date.now());
      position.value = 0;
    }
  } catch (caught) {
    toasts.error("The review could not be saved", caught instanceof ApiError ? caught.message : undefined);
  } finally {
    grading.value = false;
  }
}

async function stopReview() {
  reviewing.value = null;
  queue.value = [];
  await refresh();
}

function onKey(event: KeyboardEvent) {
  if (!reviewing.value || !card.value) return;
  const target = event.target as HTMLElement | null;
  if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
  if (!revealed.value && (event.key === " " || event.key === "Enter")) {
    event.preventDefault();
    revealed.value = true;
    return;
  }
  const chosen = GRADES.find((entry) => entry.key === event.key);
  if (chosen && revealed.value) {
    event.preventDefault();
    void grade(chosen.grade);
  }
}
onMounted(() => window.addEventListener("keydown", onKey));
onBeforeUnmount(() => window.removeEventListener("keydown", onKey));

/** "10 min", "5 h", "3 days", "2 mo", "1.5 yr": when a card would be due again. */
function formatInterval(days: number): string {
  const minutes = days * 24 * 60;
  if (minutes < 60) return `${Math.max(1, Math.round(minutes))} min`;
  if (days < 1) return `${Math.round(minutes / 60)} h`;
  if (days < 30) return `${Math.round(days)} ${Math.round(days) === 1 ? "day" : "days"}`;
  if (days < 365) return `${Math.round(days / 30)} mo`;
  return `${(days / 365).toFixed(1).replace(/\.0$/, "")} yr`;
}

function where(review: ReviewCard): string | null {
  if (review.source.page !== null) return `Page ${review.source.page}`;
  return review.source.section;
}
</script>

<template>
  <section class="decks" aria-labelledby="decks-title">
    <div v-if="reviewing" ref="reviewPanel" class="review card" tabindex="-1" aria-label="Review">
      <header class="review-head">
        <div>
          <h3>{{ reviewing.name }}</h3>
          <p class="subtle small">
            <template v-if="card">Card {{ position + 1 }} of {{ queue.length }} due</template>
            <template v-else>Done</template>
            · {{ formatNumber(reviewed) }} reviewed
          </p>
        </div>
        <button type="button" class="btn btn-ghost btn-sm" @click="stopReview"><X :size="15" /> Stop</button>
      </header>

      <div v-if="card" class="flash">
        <p class="front">{{ card.front }}</p>
        <template v-if="revealed">
          <hr />
          <p class="back">{{ card.back }}</p>
          <p v-if="where(card)" class="subtle small">{{ where(card) }}</p>
        </template>
      </div>
      <div v-else class="done">
        <PartyPopper :size="22" class="subtle" />
        <p>All caught up. Cards come back when they are due again.</p>
      </div>

      <div v-if="card" class="answers">
        <button v-if="!revealed" type="button" class="btn btn-primary reveal" @click="revealed = true">
          Show the answer <kbd>Space</kbd>
        </button>
        <template v-else>
          <button
            v-for="entry in GRADES"
            :key="entry.grade"
            type="button"
            class="btn grade"
            :class="entry.grade"
            :disabled="grading"
            @click="grade(entry.grade)"
          >
            <span>{{ entry.label }} <kbd>{{ entry.key }}</kbd></span>
            <span class="subtle small">{{ formatInterval(card.intervals[entry.grade]) }}</span>
          </button>
        </template>
      </div>
    </div>

    <template v-else>
      <div class="head">
        <h3 id="decks-title">Decks</h3>
        <p class="muted small">Save flashcards to a deck, then review the ones due each day: cards you know come back less and less often.</p>
      </div>
      <div v-if="error" class="alert alert-danger">{{ error }}</div>
      <div v-else-if="loading" class="skeleton list-skeleton" />
      <p v-else-if="!decks.length" class="empty subtle small"><Layers :size="16" /> No decks yet. Write flashcards above and save them as a deck.</p>
      <ul v-else class="list">
        <li v-for="deck in decks" :key="deck.id" class="deck card">
          <div class="deck-name">
            <strong>{{ deck.name }}</strong>
            <span class="subtle small">{{ formatNumber(deck.cards) }} {{ deck.cards === 1 ? "card" : "cards" }}</span>
          </div>
          <span class="badge" :class="{ 'badge-accent': deck.due }">{{ formatNumber(deck.due) }} due</span>
          <div class="deck-actions">
            <button type="button" class="btn btn-primary btn-sm" :disabled="!deck.due" @click="startReview(deck)">
              <Play :size="14" /> Review
            </button>
            <button type="button" class="btn btn-sm" :aria-label="`Export ${deck.name} to Anki`" @click="exportDeck(deck)">
              <Download :size="14" /> Anki
            </button>
            <button type="button" class="btn btn-ghost btn-icon btn-sm" :aria-label="`Delete ${deck.name}`" @click="remove(deck)">
              <Trash2 :size="15" />
            </button>
          </div>
        </li>
      </ul>
    </template>
  </section>
</template>

<style scoped>
.decks {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.empty {
  display: flex;
  align-items: center;
  gap: 6px;
}

.list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.deck {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 14px;
  padding: 10px 14px;
}

.deck-name {
  display: flex;
  flex: 1 1 200px;
  flex-direction: column;
  min-width: 0;
}

.deck-name strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.deck-actions {
  display: flex;
  gap: 6px;
}

.list-skeleton {
  height: 64px;
  border-radius: var(--radius);
}

.review {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px;
  outline: none;
}

.review-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.flash {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 140px;
  padding: 18px;
  border-radius: var(--radius);
  background: var(--surface-2);
  text-align: center;
}

.flash hr {
  width: 100%;
  border: 0;
  border-top: 1px solid var(--border);
}

.front {
  font-size: 18px;
  font-weight: 600;
  line-height: 1.45;
}

.back {
  font-size: 16px;
  line-height: 1.5;
  white-space: pre-line;
}

.done {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 24px;
  text-align: center;
}

.answers {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 8px;
}

.reveal {
  grid-column: 1 / -1;
  justify-content: center;
}

.grade {
  flex-direction: column;
  height: auto;
  padding: 8px 10px;
  gap: 2px;
}

.grade.again {
  border-color: var(--danger);
}

.grade.easy {
  border-color: var(--success);
}

kbd {
  margin-left: 4px;
  padding: 0 5px;
  border: 1px solid currentcolor;
  border-radius: 4px;
  font-family: inherit;
  font-size: 11px;
  opacity: 0.7;
}
</style>
