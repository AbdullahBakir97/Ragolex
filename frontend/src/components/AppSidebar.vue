<script setup lang="ts">
import { BookOpen, FolderOpen, KeyRound, LayoutGrid, LogOut, Plus, Search, X } from "@lucide/vue";
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { apiKey, setApiKey } from "@/api/auth";
import { api } from "@/api/client";
import BrandMark from "@/components/BrandMark.vue";
import HealthStatus from "@/components/HealthStatus.vue";
import NewProjectDialog from "@/components/NewProjectDialog.vue";
import ThemeToggle from "@/components/ThemeToggle.vue";
import { useProjects } from "@/composables/useProjects";

defineEmits<{ close: [] }>();

const route = useRoute();
const { names, drafts, loaded, refresh } = useProjects();
const filter = ref("");
const dialog = ref<InstanceType<typeof NewProjectDialog> | null>(null);

const current = computed(() => (typeof route.params.project === "string" ? route.params.project : null));
const visible = computed(() => {
  const query = filter.value.trim().toLowerCase();
  return query ? names.value.filter((name) => name.toLowerCase().includes(query)) : names.value;
});

// Signed in with a key: which tenant it opens.
const tenant = ref<string | null>(null);

function signOut() {
  setApiKey(null);
  window.location.assign("/");
}

onMounted(async () => {
  void refresh();
  if (apiKey.value) tenant.value = (await api.me().catch(() => null))?.tenant ?? null;
});
</script>

<template>
  <aside class="sidebar">
    <div class="head">
      <RouterLink to="/" class="brand-link" aria-label="Ragolex home"><BrandMark /></RouterLink>
      <button class="btn btn-ghost btn-icon btn-sm close" aria-label="Close navigation" @click="$emit('close')">
        <X :size="18" />
      </button>
    </div>

    <nav class="nav">
      <RouterLink to="/" class="nav-item" exact-active-class="active">
        <LayoutGrid :size="16" /> All projects
      </RouterLink>
    </nav>

    <div class="section-head">
      <span>Projects</span>
      <button class="btn btn-ghost btn-icon btn-sm" aria-label="New project" title="New project" @click="dialog?.open()">
        <Plus :size="16" />
      </button>
    </div>

    <label v-if="names.length > 6" class="filter">
      <Search :size="14" />
      <input v-model="filter" class="filter-input" placeholder="Filter projects" aria-label="Filter projects" />
    </label>

    <div class="projects">
      <template v-if="loaded">
        <RouterLink
          v-for="name in visible"
          :key="name"
          :to="{ name: 'ask', params: { project: name } }"
          class="nav-item project"
          :class="{ active: name === current }"
        >
          <FolderOpen :size="16" />
          <span class="project-name">{{ name }}</span>
          <span v-if="drafts.includes(name)" class="badge draft" title="No documents yet">new</span>
        </RouterLink>
        <p v-if="!names.length" class="empty small subtle">No projects yet.</p>
        <p v-else-if="!visible.length" class="empty small subtle">No project matches.</p>
      </template>
      <template v-else>
        <div v-for="i in 3" :key="i" class="skeleton row" />
      </template>
    </div>

    <button class="btn new" @click="dialog?.open()"><Plus :size="16" /> New project</button>

    <div class="foot">
      <div v-if="apiKey" class="signed-in small">
        <KeyRound :size="14" class="subtle" />
        <span class="tenant" :title="tenant ?? undefined">{{ tenant ?? "Signed in" }}</span>
        <button class="btn btn-ghost btn-sm" title="Forget the API key in this browser" @click="signOut">
          <LogOut :size="14" /> Sign out
        </button>
      </div>
      <HealthStatus />
      <div class="foot-row">
        <a class="nav-item docs" href="/docs" target="_blank" rel="noopener"><BookOpen :size="16" /> API docs</a>
        <ThemeToggle />
      </div>
    </div>

    <NewProjectDialog ref="dialog" />
  </aside>
</template>

<style scoped>
.signed-in {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 4px;
  color: var(--text-2);
}

.signed-in .tenant {
  flex: 1;
  overflow: hidden;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidebar {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 14px 12px;
  border-right: 1px solid var(--border);
  background: var(--surface);
  overflow: hidden;
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 2px 6px 14px;
}

.brand-link {
  color: inherit;
  text-decoration: none;
}

.close {
  display: none;
}

@media (max-width: 860px) {
  .close {
    display: inline-flex;
  }
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 34px;
  padding: 0 10px;
  border-radius: var(--radius-sm);
  color: var(--text-2);
  font-weight: 500;
  text-decoration: none;
}

.nav-item:hover {
  background: var(--surface-2);
  color: var(--text);
  text-decoration: none;
}

.nav-item.active {
  background: var(--accent-soft);
  color: var(--accent-text);
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 14px;
  padding: 0 4px 2px 10px;
  color: var(--text-3);
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.filter {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 2px 0 4px;
  padding: 0 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-3);
}

.filter:focus-within {
  border-color: var(--accent);
}

.filter-input {
  flex: 1;
  min-width: 0;
  height: 30px;
  border: 0;
  background: transparent;
  color: var(--text);
  font: inherit;
  outline: none;
  box-shadow: none;
}

.projects {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
  min-height: 0;
  overflow-y: auto;
}

.project-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.draft {
  height: 18px;
  font-size: 11px;
}

.row {
  height: 30px;
  margin: 2px 0;
}

.empty {
  padding: 6px 10px;
}

.new {
  margin: 8px 0;
}

.foot {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
}

.foot-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.docs {
  flex: 1;
}
</style>
