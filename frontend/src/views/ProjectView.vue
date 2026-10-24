<script setup lang="ts">
import {
  BarChart3,
  Bot,
  Files,
  LoaderCircle,
  MessageCircle,
  MessageSquareText,
  Search,
  Sparkles,
  TriangleAlert,
  Webhook,
} from "@lucide/vue";
import { computed, ref, toRef } from "vue";

import { ApiError, api } from "@/api/client";
import { lastConversation } from "@/composables/useConversations";
import { provideProject } from "@/composables/useProject";
import { useToasts } from "@/composables/useToasts";
import { formatNumber } from "@/lib/format";

const props = defineProps<{ project: string }>();

const { project, error, refresh } = provideProject(toRef(props, "project"));
const toasts = useToasts();
const indexing = ref(false);

const tabs = [
  { name: "ask", label: "Ask", icon: MessageSquareText },
  { name: "documents", label: "Documents", icon: Files },
  { name: "search", label: "Search", icon: Search },
  { name: "usage", label: "Usage", icon: BarChart3 },
  { name: "assistant", label: "Assistant", icon: Bot },
  { name: "widget", label: "Widget", icon: MessageCircle },
  { name: "webhooks", label: "Webhooks", icon: Webhook },
];

// The Ask tab returns to the conversation last open in this project.
function tabLink(name: string) {
  const conversation = name === "ask" ? lastConversation(props.project) : null;
  return { name, params: conversation ? { project: props.project, conversation } : { project: props.project } };
}

const unindexed = computed(() =>
  project.value ? project.value.chunks_count - project.value.embedded_chunks_count : 0,
);

async function indexNow() {
  indexing.value = true;
  try {
    const result = await api.index(props.project);
    toasts.success("Index is up to date", `${formatNumber(result.embedded_count)} chunks embedded.`);
  } catch (caught) {
    toasts.error("Indexing failed", caught instanceof ApiError ? caught.message : undefined);
  } finally {
    indexing.value = false;
    await refresh();
  }
}
</script>

<template>
  <div class="project-page">
    <header class="header">
      <div class="title-row">
        <h1 class="name">{{ props.project }}</h1>
        <div class="stats">
          <template v-if="project">
            <span class="badge">{{ formatNumber(project.files_count) }} files</span>
            <span class="badge">{{ formatNumber(project.chunks_count) }} chunks</span>
            <span v-if="project.chunks_count && !unindexed" class="badge badge-success">Indexed</span>
          </template>
          <span v-else-if="!error" class="badge">No documents</span>
        </div>
      </div>

      <nav class="tabs" aria-label="Project sections">
        <RouterLink
          v-for="tab in tabs"
          :key="tab.name"
          :to="tabLink(tab.name)"
          class="tab"
          active-class="active"
        >
          <component :is="tab.icon" :size="16" />
          {{ tab.label }}
        </RouterLink>
      </nav>
    </header>

    <div class="body">
      <div v-if="error" class="alert alert-danger">
        <TriangleAlert :size="18" />
        <span>{{ error.message }}</span>
      </div>
      <div v-if="unindexed > 0" class="alert alert-warning index-alert">
        <TriangleAlert :size="18" />
        <span class="grow">
          <strong>{{ formatNumber(unindexed) }} {{ unindexed === 1 ? "chunk is" : "chunks are" }} not indexed.</strong>
          Search and answers only use indexed chunks.
        </span>
        <button class="btn btn-sm" :disabled="indexing" @click="indexNow">
          <LoaderCircle v-if="indexing" :size="14" class="spin" />
          <Sparkles v-else :size="14" />
          {{ indexing ? "Indexing…" : "Index now" }}
        </button>
      </div>

      <RouterView v-slot="{ Component }">
        <component :is="Component" :key="props.project" />
      </RouterView>
    </div>
  </div>
</template>

<style scoped>
.project-page {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

@media (max-width: 860px) {
  .project-page {
    min-height: calc(100vh - 52px);
  }
}

.header {
  position: sticky;
  top: 0;
  z-index: 10;
  padding: 20px 32px 0;
  border-bottom: 1px solid var(--border);
  background: color-mix(in srgb, var(--bg) 88%, transparent);
  backdrop-filter: blur(8px);
}

@media (max-width: 860px) {
  .header {
    top: 52px;
    padding: 14px 16px 0;
  }
}

.title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 14px;
}

.name {
  overflow-wrap: anywhere;
}

.stats {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tabs {
  display: flex;
  gap: 4px;
  margin-top: 14px;
  overflow-x: auto;
  scrollbar-width: none;
}

.tab {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 8px 12px 10px;
  border-bottom: 2px solid transparent;
  color: var(--text-2);
  font-weight: 550;
  white-space: nowrap;
  text-decoration: none;
}

.tab:hover {
  color: var(--text);
  text-decoration: none;
}

.tab.active {
  border-bottom-color: var(--accent);
  color: var(--text);
}

@media (max-width: 480px) {
  .tab {
    gap: 5px;
    padding: 8px 8px 10px;
  }
}

.body {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 16px;
  width: 100%;
  max-width: 1120px;
  margin: 0 auto;
  padding: 20px 32px 40px;
}

@media (max-width: 640px) {
  .body {
    padding: 16px 16px 32px;
  }
}

.index-alert {
  align-items: center;
}

.grow {
  flex: 1;
}
</style>
