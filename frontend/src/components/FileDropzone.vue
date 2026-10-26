<script setup lang="ts">
import { UploadCloud } from "@lucide/vue";
import { ref } from "vue";

import { ACCEPT, SUPPORTED_LABEL } from "@/lib/fileTypes";

withDefaults(defineProps<{ large?: boolean; disabled?: boolean }>(), { large: false, disabled: false });
const emit = defineEmits<{ files: [File[]] }>();

const input = ref<HTMLInputElement | null>(null);
const over = ref(false);
let depth = 0; // dragenter/dragleave fire for every child element

function drop(event: DragEvent) {
  depth = 0;
  over.value = false;
  const files = [...(event.dataTransfer?.files ?? [])];
  if (files.length) emit("files", files);
}

function enter() {
  depth += 1;
  over.value = true;
}

function leave() {
  depth -= 1;
  if (depth <= 0) over.value = false;
}

function picked() {
  const files = [...(input.value?.files ?? [])];
  if (files.length) emit("files", files);
  if (input.value) input.value.value = "";
}
</script>

<template>
  <!-- The file input sits beside the drop zone, not in it: a button holds no other controls. -->
  <div class="dropzone-wrap">
    <div
      class="dropzone"
      :class="{ over, large, disabled }"
      role="button"
      tabindex="0"
      aria-label="Upload files: drop them here or press Enter to choose"
      @click="!disabled && input?.click()"
      @keydown.enter.prevent="!disabled && input?.click()"
      @keydown.space.prevent="!disabled && input?.click()"
      @dragenter.prevent="enter"
      @dragover.prevent
      @dragleave.prevent="leave"
      @drop.prevent="drop"
    >
      <span class="icon"><UploadCloud :size="large ? 28 : 20" /></span>
      <div>
        <p class="title"><strong>Drop files here</strong> or <span class="link">browse</span></p>
        <p class="subtle small">{{ SUPPORTED_LABEL }}</p>
      </div>
    </div>
    <input
      ref="input"
      type="file"
      class="visually-hidden"
      :accept="ACCEPT"
      multiple
      tabindex="-1"
      aria-label="Choose files to upload"
      @change="picked"
    />
  </div>
</template>

<style scoped>
.dropzone {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 18px;
  border: 1.5px dashed var(--border-strong);
  border-radius: var(--radius);
  background: var(--surface);
  cursor: pointer;
  transition:
    border-color 0.15s,
    background 0.15s;
}

.dropzone:hover,
.dropzone.over {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.dropzone.disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.dropzone.large {
  flex-direction: column;
  justify-content: center;
  min-height: 220px;
  text-align: center;
}

.icon {
  display: grid;
  flex: none;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: var(--accent-soft);
  color: var(--accent-text);
}

.large .icon {
  width: 60px;
  height: 60px;
  border-radius: 16px;
}

.over .icon {
  background: var(--surface);
}

.link {
  color: var(--accent);
  font-weight: 550;
}
</style>
