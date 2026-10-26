<script setup lang="ts">
import { MessageSquare, ThumbsDown, ThumbsUp } from "@lucide/vue";
import { ref, watch } from "vue";

import { ApiError, api } from "@/api/client";
import type { FeedbackList, Rating } from "@/api/types";
import PagerControls from "@/components/PagerControls.vue";
import { strip } from "@/lib/citations";
import { formatNumber, formatRelative } from "@/lib/format";

const props = defineProps<{ project: string }>();

const LIMIT = 10;
const filter = ref<Rating | null>(null);
const list = ref<FeedbackList | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);

async function load(offset = 0) {
  loading.value = true;
  try {
    list.value = await api.feedback(props.project, { rating: filter.value ?? undefined, offset, limit: LIMIT });
    error.value = null;
  } catch (caught) {
    const empty = caught instanceof ApiError && caught.signal === "project_not_found";
    list.value = empty ? { up: 0, down: 0, total: 0, offset: 0, limit: LIMIT, items: [] } : null;
    error.value = empty ? null : caught instanceof ApiError ? caught.message : "Feedback could not be loaded.";
  } finally {
    loading.value = false;
  }
}

const filters: { label: string; value: Rating | null }[] = [
  { label: "All", value: null },
  { label: "Good", value: "up" },
  { label: "Bad", value: "down" },
];

watch([() => props.project, filter], () => void load(), { immediate: true });
</script>

<template>
  <section class="feedback">
    <header class="head">
      <div>
        <h3>Feedback</h3>
        <p class="muted small">
          Answers rated in conversations. Export them as evaluation cases with
          <code>ragolex feedback-export {{ project }} &lt;folder&gt;</code>.
        </p>
      </div>
      <div v-if="list" class="counts">
        <span class="badge badge-success"><ThumbsUp :size="12" /> {{ formatNumber(list.up) }}</span>
        <span class="badge badge-danger"><ThumbsDown :size="12" /> {{ formatNumber(list.down) }}</span>
      </div>
    </header>

    <div class="filters" role="group" aria-label="Filter by rating">
      <button
        v-for="option in filters"
        :key="option.label"
        class="btn btn-sm"
        :class="{ 'btn-primary': filter === option.value }"
        :aria-pressed="filter === option.value"
        @click="filter = option.value"
      >
        {{ option.label }}
      </button>
    </div>

    <p v-if="error" class="alert alert-danger">{{ error }}</p>
    <template v-else-if="loading && !list">
      <div v-for="i in 2" :key="i" class="skeleton item-skeleton" />
    </template>
    <p v-else-if="list && !list.items.length" class="subtle small empty">
      {{ filter ? "No answers with this rating yet." : "No answers rated yet. Rate answers with the thumbs on the Ask page." }}
    </p>

    <ul v-if="list?.items.length" class="items">
      <li v-for="item in list.items" :key="item.message_id" class="item card">
        <span class="icon" :class="item.feedback.rating">
          <ThumbsUp v-if="item.feedback.rating === 'up'" :size="15" />
          <ThumbsDown v-else :size="15" />
        </span>
        <div class="body">
          <p class="question">{{ item.question }}</p>
          <p class="answer muted small">{{ item.answer ? strip(item.answer) : "No answer in the documents." }}</p>
          <p v-if="item.feedback.comment" class="note small">“{{ item.feedback.comment }}”</p>
          <p class="meta subtle small">
            {{ formatRelative(item.feedback.created_at) }} ·
            <RouterLink :to="{ name: 'ask', params: { project, conversation: item.conversation_id } }">
              <MessageSquare :size="12" /> Open the conversation
            </RouterLink>
          </p>
        </div>
      </li>
    </ul>

    <PagerControls
      v-if="list"
      :total="list.total"
      :offset="list.offset"
      :limit="list.limit"
      noun="rated answers"
      @change="load"
    />
  </section>
</template>

<style scoped>
.feedback {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px 16px;
}

.counts {
  display: flex;
  gap: 6px;
}

.counts .badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.filters {
  display: flex;
  gap: 6px;
}

.items {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.item {
  display: flex;
  gap: 12px;
  padding: 12px 14px;
}

.icon {
  display: grid;
  flex: none;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
}

.icon.up {
  background: var(--success-soft);
  color: var(--success);
}

.icon.down {
  background: var(--danger-soft);
  color: var(--danger);
}

.body {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.question {
  font-weight: 600;
  overflow-wrap: anywhere;
}

.answer {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
}

.note {
  color: var(--text);
  font-style: italic;
}

.meta a {
  display: inline-flex;
  align-items: center;
  gap: 3px;
}

.item-skeleton {
  height: 84px;
}

.empty {
  padding: 4px 0;
}
</style>
