<script setup lang="ts">
import { KeyRound, LoaderCircle } from "@lucide/vue";
import { nextTick, ref, watch } from "vue";

import { apiKey, keyNeeded, setApiKey } from "@/api/auth";
import { ApiError, api } from "@/api/client";

const dialog = ref<HTMLDialogElement | null>(null);
const input = ref<HTMLInputElement | null>(null);
const key = ref("");
const checking = ref(false);
const error = ref<string | null>(null);

watch(
  keyNeeded,
  async (needed) => {
    if (!needed) return;
    // A key that was refused is no use any more.
    error.value = apiKey.value ? "The saved API key no longer works." : null;
    setApiKey(null);
    key.value = "";
    await nextTick();
    if (!dialog.value?.open) dialog.value?.showModal();
    input.value?.focus();
  },
  { flush: "post" },
);

async function signIn() {
  const value = key.value.trim();
  if (!value) return;
  checking.value = true;
  error.value = null;
  setApiKey(value);
  try {
    await api.me();
    keyNeeded.value = false;
    dialog.value?.close();
    // Everything on the page was loaded without the key: start again with it.
    window.location.reload();
  } catch (caught) {
    setApiKey(null);
    keyNeeded.value = true;
    error.value = caught instanceof ApiError ? caught.message : "The key could not be checked.";
  } finally {
    checking.value = false;
  }
}
</script>

<template>
  <dialog ref="dialog" class="dialog" aria-labelledby="api-key-title" @cancel.prevent>
    <form class="content" @submit.prevent="signIn">
      <span class="icon"><KeyRound :size="20" /></span>
      <h2 id="api-key-title">Sign in with an API key</h2>
      <p class="muted">
        This server needs an API key. Ask its administrator for one, or create one on the server with
        <code>ragolex keys create</code>. It is kept in this browser only.
      </p>
      <label class="field">
        <span>API key</span>
        <input
          ref="input"
          v-model="key"
          class="input mono"
          type="password"
          placeholder="mrag_…"
          autocomplete="off"
          spellcheck="false"
          :aria-invalid="!!error"
        />
      </label>
      <p v-if="error" class="error small" role="alert">{{ error }}</p>
      <div class="actions">
        <button type="submit" class="btn btn-primary" :disabled="checking || !key.trim()">
          <LoaderCircle v-if="checking" :size="16" class="spin" />
          Sign in
        </button>
      </div>
    </form>
  </dialog>
</template>

<style scoped>
.dialog {
  width: min(440px, calc(100vw - 32px));
  padding: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
  color: var(--text);
  box-shadow: var(--shadow-lg);
}

.dialog::backdrop {
  background: rgb(0 0 0 / 50%);
}

.content {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 22px;
}

.icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: var(--accent-soft);
  color: var(--accent);
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: 550;
}

.error {
  color: var(--danger);
}

.actions {
  display: flex;
  justify-content: flex-end;
}
</style>
