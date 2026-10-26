<script setup lang="ts">
import { ArrowRight, FileText, FolderPlus, MessageSquareText, Plus, Sparkles, Upload } from "@lucide/vue";
import { onMounted, ref, watch } from "vue";

import { ApiError, api } from "@/api/client";
import type { Project } from "@/api/types";
import NewProjectDialog from "@/components/NewProjectDialog.vue";
import PageHeader from "@/components/PageHeader.vue";
import { useProjects } from "@/composables/useProjects";
import { formatNumber, formatPercent, formatRelative } from "@/lib/format";
import { signalMessage } from "@/lib/signals";

const { projects, drafts, loaded, error, refresh } = useProjects();
const details = ref<Record<string, Project>>({});
const dialog = ref<InstanceType<typeof NewProjectDialog> | null>(null);

// The cards show counts, which the list does not carry: load them per project.
watch(projects, async (list) => {
  const loadedDetails = await Promise.all(
    list.slice(0, 48).map((project) => api.project(project.name).catch(() => null)),
  );
  details.value = Object.fromEntries(loadedDetails.filter((p): p is Project => !!p).map((p) => [p.name, p]));
});

onMounted(refresh);

const steps = [
  { icon: Upload, title: "Upload", text: "Add PDF, Word, Markdown, HTML, text or source code files to a project." },
  { icon: Sparkles, title: "Index", text: "They are split into chunks and embedded for search by meaning." },
  { icon: MessageSquareText, title: "Ask", text: "Get answers that cite the passages they come from." },
];
</script>

<template>
  <div class="page">
    <PageHeader title="Projects" subtitle="Each project is a set of documents you can search and ask questions about.">
      <template #actions>
        <button class="btn btn-primary" @click="dialog?.open()"><Plus :size="16" /> New project</button>
      </template>
    </PageHeader>

    <div v-if="error" class="alert alert-danger">
      <span>{{ error instanceof ApiError ? error.message : signalMessage("network_error") }}</span>
    </div>

    <div v-if="!loaded" class="grid">
      <div v-for="i in 3" :key="i" class="skeleton card-skeleton" />
    </div>

    <section v-else-if="!projects.length && !drafts.length" class="welcome card">
      <div class="welcome-icon"><FolderPlus :size="26" /></div>
      <h2>Create your first project</h2>
      <p class="muted">Upload documents, and ask questions that are answered from them, with sources.</p>
      <ol class="steps">
        <li v-for="(step, i) in steps" :key="step.title" class="step">
          <span class="step-icon"><component :is="step.icon" :size="18" /></span>
          <div>
            <h3>{{ i + 1 }}. {{ step.title }}</h3>
            <p class="muted small">{{ step.text }}</p>
          </div>
        </li>
      </ol>
      <button class="btn btn-primary" @click="dialog?.open()"><Plus :size="16" /> New project</button>
    </section>

    <div v-else class="grid">
      <RouterLink
        v-for="project in projects"
        :key="project.name"
        :to="{ name: 'ask', params: { project: project.name } }"
        class="project card"
      >
        <div class="project-head">
          <span class="project-icon"><FileText :size="18" /></span>
          <h2 class="project-name">{{ project.name }}</h2>
          <ArrowRight :size="16" class="arrow" />
        </div>
        <dl v-if="details[project.name]" class="counts">
          <div>
            <dt>Files</dt>
            <dd>{{ formatNumber(details[project.name]!.files_count) }}</dd>
          </div>
          <div>
            <dt>Chunks</dt>
            <dd>{{ formatNumber(details[project.name]!.chunks_count) }}</dd>
          </div>
          <div>
            <dt>Indexed</dt>
            <dd>
              {{ formatPercent(details[project.name]!.embedded_chunks_count, details[project.name]!.chunks_count) }}
            </dd>
          </div>
        </dl>
        <div v-else class="skeleton counts-skeleton" />
        <p class="subtle small">Created {{ formatRelative(project.created_at) }}</p>
      </RouterLink>

      <RouterLink
        v-for="name in drafts"
        :key="name"
        :to="{ name: 'documents', params: { project: name } }"
        class="project card draft"
      >
        <div class="project-head">
          <span class="project-icon"><FolderPlus :size="18" /></span>
          <h2 class="project-name">{{ name }}</h2>
          <ArrowRight :size="16" class="arrow" />
        </div>
        <p class="muted small">No documents yet. Upload one to save the project.</p>
      </RouterLink>
    </div>

    <NewProjectDialog ref="dialog" />
  </div>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 20px;
  max-width: 1120px;
  margin: 0 auto;
  padding: 28px 32px 48px;
}

@media (max-width: 640px) {
  .page {
    padding: 20px 16px 40px;
  }
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 14px;
}

.card-skeleton {
  height: 150px;
  border-radius: var(--radius);
}

.project {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px;
  color: inherit;
  text-decoration: none;
  transition:
    border-color 0.15s,
    box-shadow 0.15s,
    transform 0.15s;
}

.project:hover {
  border-color: var(--border-strong);
  box-shadow: var(--shadow);
  text-decoration: none;
  transform: translateY(-1px);
}

.project.draft {
  border-style: dashed;
  box-shadow: none;
}

.project-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.project-icon {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: var(--radius-sm);
  background: var(--accent-soft);
  color: var(--accent-text);
}

.project-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.arrow {
  color: var(--text-3);
  transition: transform 0.15s;
}

.project:hover .arrow {
  color: var(--accent);
  transform: translateX(2px);
}

.counts {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  margin: 0;
  padding: 10px 0;
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
}

.counts dt {
  color: var(--text-3);
  font-size: 12px;
}

.counts dd {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.counts-skeleton {
  height: 56px;
}

.welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 40px 24px;
  text-align: center;
}

.welcome-icon {
  display: grid;
  place-items: center;
  width: 56px;
  height: 56px;
  margin-bottom: 4px;
  border-radius: 16px;
  background: var(--accent-soft);
  color: var(--accent-text);
}

.steps {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  width: 100%;
  max-width: 760px;
  margin: 18px 0;
  padding: 0;
  list-style: none;
  text-align: left;
}

@media (max-width: 720px) {
  .steps {
    grid-template-columns: 1fr;
  }
}

.step {
  display: flex;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-2);
}

.step-icon {
  display: grid;
  flex: none;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: var(--surface);
  color: var(--accent);
  box-shadow: var(--shadow-sm);
}
</style>
