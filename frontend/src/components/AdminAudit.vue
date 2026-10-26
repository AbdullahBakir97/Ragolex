<script setup lang="ts">
import { Search } from "@lucide/vue";
import { onMounted, ref } from "vue";

import { ApiError, api } from "@/api/client";
import type { AuditEvent, Page } from "@/api/types";
import PagerControls from "@/components/PagerControls.vue";
import { formatDate } from "@/lib/format";

// The tenant's audit log: who changed what, most recent first.
const LIMIT = 20;
const page = ref<Page<AuditEvent> | null>(null);
const action = ref("");
const error = ref<string | null>(null);

async function load(offset = 0) {
  try {
    page.value = await api.audit({ offset, limit: LIMIT }, action.value.trim() || undefined);
    error.value = null;
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "The audit log could not be loaded.";
  }
}
onMounted(() => load());
defineExpose({ refresh: () => load(page.value?.offset ?? 0) });

/** Who did it, then the details. */
function byline(event: AuditEvent): string {
  const who = event.actor ? `By ${event.actor.name ?? event.actor.key_id}` : "By the server's operators";
  return Object.keys(event.details).length ? `${who} · ${describe(event.details)}` : who;
}

/** The details as short `key: value` pairs. */
function describe(details: Record<string, unknown>): string {
  return Object.entries(details)
    .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(", ") : typeof value === "object" ? JSON.stringify(value) : String(value)}`)
    .join(" · ");
}
</script>

<template>
  <section class="audit" aria-labelledby="audit-title">
    <div class="head">
      <div>
        <h3 id="audit-title">Audit log</h3>
        <p class="muted small">Keys, webhooks, widgets, deletions and limits: what changed, and the key that changed it.</p>
      </div>
      <form class="filter" role="search" @submit.prevent="load()">
        <label class="visually-hidden" for="audit-action">Action</label>
        <input id="audit-action" v-model="action" class="input" placeholder="Action, e.g. api_key" maxlength="64" />
        <button type="submit" class="btn btn-icon" aria-label="Filter the audit log"><Search :size="15" /></button>
      </form>
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-else-if="!page" class="skeleton list-skeleton" />
    <p v-else-if="!page.items.length" class="subtle small">Nothing recorded{{ action.trim() ? ` for “${action.trim()}”` : "" }}.</p>
    <ol v-else class="events card">
      <li v-for="event in page.items" :key="event.id" class="event">
        <div class="line">
          <span class="mono action">{{ event.action }}</span>
          <span v-if="event.target" class="target">{{ event.target }}</span>
          <time class="subtle small" :datetime="event.created_at">{{ formatDate(event.created_at) }}</time>
        </div>
        <div class="subtle small">{{ byline(event) }}</div>
      </li>
    </ol>
    <PagerControls v-if="page" :total="page.total" :offset="page.offset" :limit="page.limit" noun="events" @change="load" />
  </section>
</template>

<style scoped>
.audit {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 10px;
}

.filter {
  display: flex;
  gap: 6px;
  width: min(280px, 100%);
}

.events {
  margin: 0;
  padding: 0;
  list-style: none;
}

.event {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  overflow-wrap: anywhere;
}

.event:last-child {
  border-bottom: 0;
}

.line {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 10px;
}

.action {
  font-weight: 600;
}

.target {
  color: var(--text-2);
}

.line time {
  margin-left: auto;
}

.list-skeleton {
  height: 180px;
  border-radius: var(--radius);
}
</style>
