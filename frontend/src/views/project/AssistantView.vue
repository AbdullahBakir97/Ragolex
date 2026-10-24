<script setup lang="ts">
import { Bot, Check, LoaderCircle, ShieldCheck } from "@lucide/vue";
import { computed, onMounted, ref, watch } from "vue";

import { ApiError, api } from "@/api/client";
import { useProject } from "@/composables/useProject";
import { useToasts } from "@/composables/useToasts";

const MAX_NAME = 60;
const MAX_INSTRUCTIONS = 4000;
const EXAMPLES = [
  "Be warm and brief, and address the reader as “you”.",
  "Answer in bullet points when there are several steps.",
  "When the documents do not cover a question, suggest writing to support@example.com.",
];

const { name: project } = useProject();
const toasts = useToasts();

const loading = ref(true);
const missing = ref(false);
const saving = ref(false);
const saved = ref({ name: "", instructions: "" });
const form = ref({ name: "", instructions: "" });
const changed = computed(
  () => form.value.name.trim() !== saved.value.name || form.value.instructions.trim() !== saved.value.instructions,
);

async function load() {
  loading.value = true;
  try {
    const assistant = await api.assistant(project.value);
    saved.value = { name: assistant.name ?? "", instructions: assistant.instructions ?? "" };
    form.value = { ...saved.value };
    missing.value = false;
  } catch (caught) {
    missing.value = caught instanceof ApiError && caught.signal === "project_not_found";
    if (!missing.value) toasts.error("The assistant could not be loaded", caught instanceof ApiError ? caught.message : undefined);
  } finally {
    loading.value = false;
  }
}

async function save() {
  saving.value = true;
  try {
    const assistant = await api.updateAssistant(project.value, {
      name: form.value.name.trim() || null,
      instructions: form.value.instructions.trim() || null,
    });
    saved.value = { name: assistant.name ?? "", instructions: assistant.instructions ?? "" };
    form.value = { ...saved.value };
    toasts.success("Assistant saved", "New answers follow it, in the web app, the widgets and the API.");
  } catch (caught) {
    toasts.error("The assistant could not be saved", caught instanceof ApiError ? caught.message : undefined);
  } finally {
    saving.value = false;
  }
}

function addExample(example: string) {
  const text = form.value.instructions.trim();
  form.value.instructions = text ? `${text}\n${example}` : example;
}

watch(project, load);
onMounted(load);
</script>

<template>
  <section class="assistant">
    <div>
      <h2>Assistant</h2>
      <p class="muted small">
        Give the assistant that answers from this project a name and a voice. It applies to every answer: here, in the
        chat widgets, and through the API.
      </p>
    </div>

    <div v-if="loading" class="card skeleton form-skeleton" />
    <p v-else-if="missing" class="subtle small">Upload a document first: the project is saved with its first file.</p>
    <form v-else class="card form" @submit.prevent="save">
      <label class="field">
        <span>Name</span>
        <input
          v-model="form.name"
          class="input"
          :maxlength="MAX_NAME"
          placeholder="e.g. Ada, the handbook assistant"
          autocomplete="off"
        />
        <span class="subtle small">The name it goes by when asked. Leave empty for none.</span>
      </label>
      <label class="field">
        <span>Instructions</span>
        <textarea
          v-model="form.instructions"
          class="input"
          rows="7"
          :maxlength="MAX_INSTRUCTIONS"
          placeholder="How should answers sound? What should they always mention?"
        />
        <span class="counter subtle small">{{ form.instructions.length }} / {{ MAX_INSTRUCTIONS }}</span>
      </label>
      <div class="examples">
        <span class="small muted">Examples:</span>
        <button v-for="example in EXAMPLES" :key="example" type="button" class="badge example" @click="addExample(example)">
          + {{ example }}
        </button>
      </div>
      <p class="note small">
        <ShieldCheck :size="15" aria-hidden="true" />
        Instructions shape tone, style and what answers mention. They never override the rules: answers still come only
        from the project's documents, with citations, and say so when the documents don't answer.
      </p>
      <div class="actions">
        <button v-if="changed" type="button" class="btn btn-ghost" @click="form = { ...saved }">Undo changes</button>
        <button class="btn btn-primary" type="submit" :disabled="saving || !changed">
          <LoaderCircle v-if="saving" :size="16" class="spin" />
          <Check v-else :size="16" />
          Save
        </button>
      </div>
    </form>

    <div v-if="!loading && !missing && saved.name" class="preview card small">
      <Bot :size="16" aria-hidden="true" />
      <span>Answers introduce the assistant as <strong>{{ saved.name }}</strong> when asked who it is.</span>
    </div>
  </section>
</template>

<style scoped>
.assistant {
  display: flex;
  flex-direction: column;
  gap: 14px;
  max-width: 760px;
}

.form {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px;
}

.form-skeleton {
  height: 320px;
}

.field textarea {
  resize: vertical;
}

.counter {
  align-self: flex-end;
}

.examples {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.example {
  border: 1px solid var(--border);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
  white-space: normal;
  height: auto;
  min-height: 22px;
  text-align: left;
}

.example:hover {
  border-color: var(--accent);
  color: var(--accent-text);
}

.note {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  margin: 0;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  color: var(--text-2);
}

.note svg {
  flex: none;
  margin-top: 1px;
  color: var(--success);
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.preview {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  color: var(--text-2);
}
</style>
