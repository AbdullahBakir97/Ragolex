<script setup lang="ts">
import { Check, Code, Copy, LoaderCircle, MessageCircle, Pencil, Plus, Trash2 } from "@lucide/vue";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

import { ApiError, api } from "@/api/client";
import type { ChatWidget as Widget, ChatWidgetSettings } from "@/api/types";
import TagInput from "@/components/TagInput.vue";
import { useProject } from "@/composables/useProject";
import { useToasts } from "@/composables/useToasts";
import { formatRelative } from "@/lib/format";
import { WidgetError } from "@/widget/client";
import { ChatWidget } from "@/widget/widget";

const { name, tags: projectTags } = useProject();
const tagSuggestions = computed(() => projectTags.value.map((t) => t.tag));
const toasts = useToasts();

const DEFAULT_ACCENT = "#2563eb";

const widgets = ref<Widget[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);
const noProject = ref(false);

async function load() {
  loading.value = true;
  try {
    widgets.value = (await api.widgets(name.value)).items;
    error.value = null;
    noProject.value = false;
  } catch (caught) {
    widgets.value = [];
    noProject.value = caught instanceof ApiError && caught.signal === "project_not_found";
    error.value = noProject.value ? null : caught instanceof ApiError ? caught.message : "Widgets could not be loaded.";
  } finally {
    loading.value = false;
  }
  if (!widgets.value.some((widget) => widget.id === previewed.value)) previewed.value = widgets.value[0]?.id ?? null;
}

// The form: a new widget, or the one being edited.
const editing = ref<Widget | null>(null);
const form = ref({ name: "", welcome: "", accent: DEFAULT_ACCENT, origins: "", tags: [] as string[], logo: "" });
const tagInput = ref<InstanceType<typeof TagInput> | null>(null);
const saving = ref(false);

function resetForm() {
  editing.value = null;
  form.value = { name: "", welcome: "", accent: DEFAULT_ACCENT, origins: "", tags: [], logo: "" };
}

function edit(widget: Widget) {
  editing.value = widget;
  form.value = {
    name: widget.name,
    welcome: widget.welcome ?? "",
    accent: widget.accent,
    origins: widget.allowed_origins.join("\n"),
    tags: [...widget.tags],
    logo: widget.logo_url ?? "",
  };
}

const origins = computed(() =>
  form.value.origins
    .split(/[\s,]+/)
    .map((origin) => origin.trim())
    .filter(Boolean),
);
const validAccent = computed(() => /^#[0-9a-fA-F]{6}$/.test(form.value.accent));
const validLogo = computed(() => !form.value.logo.trim() || /^https:\/\/[^\s/]+\S*$/i.test(form.value.logo.trim()));

async function save() {
  if (tagInput.value && !tagInput.value.commit()) return;
  const settings: ChatWidgetSettings = {
    name: form.value.name.trim(),
    welcome: form.value.welcome.trim() || null,
    accent: form.value.accent,
    allowed_origins: origins.value,
    tags: form.value.tags,
    logo_url: form.value.logo.trim() || null,
  };
  saving.value = true;
  try {
    if (editing.value) {
      const saved = await api.updateWidget(name.value, editing.value.id, settings);
      toasts.success("Widget saved", "Pages that embed it show the change when they are next loaded.");
      previewed.value = saved.id;
    } else {
      const saved = await api.createWidget(name.value, settings);
      toasts.success("Widget added", "Copy its script tag into your website's pages.");
      previewed.value = saved.id;
    }
    resetForm();
    await load();
    previewVersion.value += 1;
  } catch (caught) {
    toasts.error("The widget could not be saved", caught instanceof ApiError ? caught.message : undefined);
  } finally {
    saving.value = false;
  }
}

// Each widget's actions.
const confirmingDelete = ref<string | null>(null);
const busy = ref<string | null>(null);
const copied = ref<string | null>(null);

function scriptTag(widget: Widget): string {
  return `<script src="${window.location.origin}/widget.js" data-widget="${widget.id}" async></` + "script>";
}

async function copy(widget: Widget) {
  try {
    await navigator.clipboard.writeText(scriptTag(widget));
    copied.value = widget.id;
  } catch {
    toasts.error("Copying failed", "Select the script tag and copy it by hand.");
  }
}

async function remove(widget: Widget) {
  busy.value = widget.id;
  try {
    await api.deleteWidget(name.value, widget.id);
    toasts.success("Widget removed", "Pages that embed it no longer show it.");
    if (editing.value?.id === widget.id) resetForm();
    await load();
  } catch (caught) {
    toasts.error("The widget could not be removed", caught instanceof ApiError ? caught.message : undefined);
  } finally {
    busy.value = null;
    confirmingDelete.value = null;
  }
}

// The preview: the real widget, inline, asking through its public API.
const previewed = ref<string | null>(null);
const previewVersion = ref(0);
const previewHost = ref<HTMLElement | null>(null);
const previewError = ref<string | null>(null);
let preview: ChatWidget | null = null;
// Counts the previews started, so only the latest one stays when they overlap.
let previews = 0;

async function showPreview() {
  const run = ++previews;
  preview?.destroy();
  preview = null;
  previewError.value = null;
  await nextTick();
  const widgetId = previewed.value;
  if (!widgetId || !previewHost.value) return;
  try {
    const mounted = await ChatWidget.mount({
      widgetId,
      apiBase: window.location.origin,
      container: previewHost.value,
      storage: null,
    });
    if (run === previews) preview = mounted;
    else mounted.destroy();
  } catch (caught) {
    if (run !== previews) return;
    previewError.value = caught instanceof WidgetError ? `The preview could not load (${caught.signal}).` : "The preview could not load.";
  }
}

watch([previewed, previewVersion], showPreview);
watch(name, () => {
  resetForm();
  previewed.value = null;
  void load();
});
onMounted(load);
onBeforeUnmount(() => {
  previews += 1;
  preview?.destroy();
});
</script>

<template>
  <section class="widget-page">
    <div>
      <h2>Chat widget</h2>
      <p class="muted small">
        Let the visitors of your website ask this project's documents. Add a widget, then paste its script tag into your
        pages: a chat button appears in the corner, with answers streamed as they are written and their sources one click
        away. Visitors need no API key; their questions count against this tenant's limits.
      </p>
    </div>

    <div v-if="noProject" class="empty card">
      <MessageCircle :size="22" class="subtle" />
      <p class="muted">Upload documents to this project first; the widget answers from them.</p>
    </div>

    <div v-else class="layout">
      <div class="column">
        <form class="card settings" @submit.prevent="save">
          <h3>{{ editing ? `Edit ${editing.name}` : "New widget" }}</h3>
          <label class="field">
            <span>Name</span>
            <input v-model="form.name" class="input" required maxlength="100" placeholder="Handbook assistant" />
            <span class="subtle small">Shown in the widget's header.</span>
          </label>
          <label class="field">
            <span>Welcome message <span class="subtle">(optional)</span></span>
            <textarea v-model="form.welcome" class="input" rows="2" maxlength="500" placeholder="Hi! Ask me anything about our handbook." />
          </label>
          <div class="field">
            <label for="widget-accent">Colour</label>
            <div class="accent">
              <input v-model="form.accent" type="color" aria-label="Pick the colour" class="swatch-input" />
              <input id="widget-accent" v-model="form.accent" class="input mono" maxlength="7" pattern="#[0-9a-fA-F]{6}" />
            </div>
          </div>
          <label class="field">
            <span>Allowed websites</span>
            <textarea
              v-model="form.origins"
              class="input mono"
              rows="3"
              required
              placeholder="https://example.com&#10;https://www.example.com"
            />
            <span class="subtle small">
              One per line: scheme, host and any port, like <code>https://example.com</code>. Pages on other websites are
              refused; <code>*</code> allows any website.
            </span>
          </label>
          <label class="field">
            <span>Logo <span class="subtle">(optional)</span></span>
            <div class="logo-field">
              <img v-if="validLogo && form.logo.trim()" :src="form.logo.trim()" alt="" class="logo-preview" referrerpolicy="no-referrer" />
              <input
                v-model="form.logo"
                class="input"
                type="url"
                maxlength="2000"
                placeholder="https://example.com/logo.png"
                :aria-invalid="!validLogo"
              />
            </div>
            <span class="small" :class="validLogo ? 'subtle' : 'error-text'">
              {{ validLogo ? "An https address of a square image, shown in the widget's header." : "Use an https address." }}
            </span>
          </label>
          <div class="field">
            <span>Answer only from documents tagged</span>
            <TagInput
              ref="tagInput"
              v-model="form.tags"
              :suggestions="tagSuggestions"
              label="Answer only from documents tagged"
              placeholder="Any document"
            />
            <span class="subtle small">With tags, visitors get answers only from documents with at least one of them.</span>
          </div>
          <div class="actions">
            <button v-if="editing" type="button" class="btn btn-ghost" @click="resetForm">Cancel</button>
            <button
              class="btn btn-primary"
              type="submit"
              :disabled="saving || !form.name.trim() || !origins.length || !validAccent || !validLogo"
            >
              <LoaderCircle v-if="saving" :size="16" class="spin" />
              <Check v-else-if="editing" :size="16" />
              <Plus v-else :size="16" />
              {{ editing ? "Save" : "Add widget" }}
            </button>
          </div>
        </form>

        <div v-if="error" class="alert alert-danger">{{ error }}</div>
        <div v-else-if="loading" class="skeleton list-skeleton" />
        <ul v-else-if="widgets.length" class="list">
          <li v-for="widget in widgets" :key="widget.id" class="card item" :class="{ selected: previewed === widget.id }">
            <div class="row">
              <img v-if="widget.logo_url" :src="widget.logo_url" alt="" class="swatch logo-swatch" referrerpolicy="no-referrer" />
              <span v-else class="swatch" :style="{ background: widget.accent }" aria-hidden="true" />
              <div class="info">
                <p class="name">{{ widget.name }}</p>
                <p class="subtle small">added {{ formatRelative(widget.created_at) }}</p>
              </div>
              <div v-if="confirmingDelete === widget.id" class="confirm">
                <span class="small">Remove from every page?</span>
                <button class="btn btn-danger btn-sm" :disabled="busy !== null" @click="remove(widget)">Remove</button>
                <button class="btn btn-ghost btn-sm" @click="confirmingDelete = null">Cancel</button>
              </div>
              <div v-else class="buttons">
                <button v-if="previewed !== widget.id" class="btn btn-sm" @click="previewed = widget.id">Preview</button>
                <button class="btn btn-ghost btn-icon btn-sm" :aria-label="`Edit ${widget.name}`" title="Edit" @click="edit(widget)">
                  <Pencil :size="15" />
                </button>
                <button
                  class="btn btn-ghost btn-icon btn-sm"
                  :aria-label="`Remove ${widget.name}`"
                  title="Remove"
                  @click="confirmingDelete = widget.id"
                >
                  <Trash2 :size="15" />
                </button>
              </div>
            </div>
            <div class="badges">
              <span v-for="origin in widget.allowed_origins" :key="origin" class="badge mono">{{
                origin === "*" ? "any website" : origin
              }}</span>
              <span v-for="tag in widget.tags" :key="tag" class="chip" :title="`Answers only from documents tagged ${tag}`">{{
                tag
              }}</span>
            </div>
            <div class="embed">
              <Code :size="14" class="subtle" aria-hidden="true" />
              <code class="snippet">{{ scriptTag(widget) }}</code>
              <button class="btn btn-sm" :aria-label="`Copy the script tag of ${widget.name}`" @click="copy(widget)">
                <Check v-if="copied === widget.id" :size="14" />
                <Copy v-else :size="14" />
                {{ copied === widget.id ? "Copied" : "Copy" }}
              </button>
            </div>
          </li>
        </ul>
        <p v-else class="subtle small">No widgets yet.</p>
      </div>

      <aside class="card preview" aria-label="Preview">
        <div class="preview-head">
          <h3>Preview</h3>
          <span class="subtle small">A real conversation: it counts as one, and shows under Ask.</span>
        </div>
        <div v-if="previewError" class="alert alert-danger small">{{ previewError }}</div>
        <p v-else-if="!previewed" class="subtle small preview-empty">Add a widget to try it here.</p>
        <div ref="previewHost" class="preview-host" />
      </aside>
    </div>
  </section>
</template>

<style scoped>
.logo-field {
  display: flex;
  align-items: center;
  gap: 8px;
}

.logo-swatch {
  object-fit: cover;
}

.logo-preview {
  width: 34px;
  height: 34px;
  flex: none;
  border: 1px solid var(--border);
  border-radius: 8px;
  object-fit: cover;
}

.error-text {
  color: var(--danger);
}

.widget-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 400px);
  gap: 16px;
  align-items: start;
}

@media (max-width: 960px) {
  .layout {
    grid-template-columns: minmax(0, 1fr);
  }
}

.column {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
}

.settings {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
}

.settings h3,
.preview h3 {
  margin: 0;
  font-size: 15px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: 550;
}

.field .input {
  width: 100%;
}

.field textarea {
  resize: vertical;
}

.accent {
  display: flex;
  gap: 8px;
  align-items: center;
}

.accent .input {
  max-width: 120px;
}

.swatch-input {
  width: 40px;
  height: 34px;
  padding: 2px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  cursor: pointer;
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.item {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px 14px;
}

.item.selected {
  border-color: var(--accent);
}

.row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.swatch {
  width: 22px;
  height: 22px;
  flex: none;
  border-radius: 50%;
}

.info {
  flex: 1;
  min-width: 140px;
}

.info p {
  margin: 0;
}

.name {
  font-weight: 600;
}

.buttons,
.confirm {
  display: flex;
  align-items: center;
  gap: 6px;
}

.badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.embed {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--surface-2, var(--surface));
}

.snippet {
  flex: 1;
  min-width: 0;
  overflow-x: auto;
  white-space: nowrap;
  font-size: 12px;
}

.preview {
  position: sticky;
  top: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
}

.preview-head {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.preview-empty {
  margin: 0;
}

.preview-host {
  height: 540px;
}

.preview-host:empty {
  display: none;
}

.list-skeleton {
  height: 120px;
}

.empty {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px;
}
</style>
