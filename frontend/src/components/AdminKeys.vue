<script setup lang="ts">
import { Check, Copy, KeyRound, Plus } from "@lucide/vue";
import { onMounted, ref } from "vue";

import { ApiError, api } from "@/api/client";
import { SCOPES, type ApiKeyInfo, type CreatedApiKey, type Scope } from "@/api/types";
import { useToasts } from "@/composables/useToasts";
import { formatRelative } from "@/lib/format";

// The tenant's API keys: create one (its secret shown once) or revoke one.
const props = defineProps<{ currentKeyId: string | null }>();
// A key was created or revoked: the audit log has a new event.
const emit = defineEmits<{ changed: [] }>();

const SCOPE_HELP: Record<Scope, string> = {
  read: "List and search",
  write: "Upload, process, index and delete",
  ask: "Questions and conversations",
  admin: "Keys, webhooks, widgets and the audit log",
};

const toasts = useToasts();
const keys = ref<ApiKeyInfo[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);

const name = ref("");
const scopes = ref<Scope[]>(["read", "ask"]);
const creating = ref(false);
const created = ref<CreatedApiKey | null>(null);
const copied = ref(false);

async function load() {
  try {
    keys.value = await api.keys();
    error.value = null;
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "The keys could not be loaded.";
  } finally {
    loading.value = false;
  }
}
onMounted(load);

async function create() {
  if (!name.value.trim() || !scopes.value.length || creating.value) return;
  creating.value = true;
  try {
    created.value = await api.createKey(name.value.trim(), [...scopes.value]);
    copied.value = false;
    name.value = "";
    emit("changed");
    await load();
  } catch (caught) {
    toasts.error("The key could not be created", caught instanceof ApiError ? caught.message : undefined);
  } finally {
    creating.value = false;
  }
}

async function copy() {
  if (!created.value) return;
  try {
    await navigator.clipboard.writeText(created.value.key);
    copied.value = true;
  } catch {
    toasts.error("Copying failed", "Select the key and copy it by hand.");
  }
}

async function revoke(key: ApiKeyInfo) {
  const own = key.id === props.currentKeyId;
  const warning = own ? " This is the key this browser uses: you will be signed out." : "";
  if (!window.confirm(`Revoke “${key.name}”? It stops working at once.${warning}`)) return;
  try {
    await api.revokeKey(key.id);
    toasts.success("Key revoked", `“${key.name}” no longer works.`);
    emit("changed");
    await load();
  } catch (caught) {
    toasts.error("The key could not be revoked", caught instanceof ApiError ? caught.message : undefined);
  }
}
</script>

<template>
  <section class="keys" aria-labelledby="keys-title">
    <div>
      <h3 id="keys-title">API keys</h3>
      <p class="muted small">Each app or person gets its own key, with only the scopes it needs. Only a hash is stored: a new key is shown once.</p>
    </div>

    <form class="create card" @submit.prevent="create">
      <label class="field name">
        <span>Name</span>
        <input v-model="name" class="input" maxlength="100" placeholder="e.g. Support bot" required />
      </label>
      <fieldset class="field">
        <legend>Scopes</legend>
        <div class="scopes">
          <label v-for="scope in SCOPES" :key="scope" class="scope" :title="SCOPE_HELP[scope]">
            <input v-model="scopes" type="checkbox" :value="scope" />
            {{ scope }}
          </label>
        </div>
      </fieldset>
      <button type="submit" class="btn btn-primary" :disabled="creating || !scopes.length || !name.trim()">
        <Plus :size="15" /> Create key
      </button>
    </form>

    <div v-if="created" class="alert alert-success created" role="status">
      <KeyRound :size="18" />
      <div class="created-body">
        <strong>“{{ created.name }}” is ready. Copy the key now: it is not shown again.</strong>
        <div class="secret">
          <code class="mono" data-testid="new-key">{{ created.key }}</code>
          <button type="button" class="btn btn-sm" @click="copy">
            <component :is="copied ? Check : Copy" :size="14" /> {{ copied ? "Copied" : "Copy" }}
          </button>
        </div>
      </div>
      <button type="button" class="btn btn-ghost btn-sm" @click="created = null">Done</button>
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-else-if="loading" class="skeleton table-skeleton" />
    <div v-else class="table-wrap card">
      <table class="table">
        <caption class="visually-hidden">API keys</caption>
        <thead>
          <tr>
            <th scope="col">Name</th>
            <th scope="col">Scopes</th>
            <th scope="col" class="hide-sm">Last used</th>
            <th scope="col" class="hide-sm">Created</th>
            <th scope="col"><span class="visually-hidden">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!keys.length">
            <td colspan="5" class="subtle">No keys yet. With authentication off, the API needs none.</td>
          </tr>
          <tr v-for="key in keys" :key="key.id" :class="{ revoked: key.revoked_at }">
            <td>
              <span class="key-name">{{ key.name }}</span>
              <span class="mono subtle small">{{ key.prefix }}…</span>
              <span v-if="key.id === currentKeyId" class="badge badge-accent">This browser</span>
              <span v-if="key.revoked_at" class="badge">Revoked</span>
            </td>
            <td>
              <span class="scope-list">
                <span v-for="scope in key.scopes" :key="scope" class="chip">{{ scope }}</span>
              </span>
            </td>
            <td class="hide-sm subtle small">{{ key.last_used_at ? formatRelative(key.last_used_at) : "Never" }}</td>
            <td class="hide-sm subtle small">{{ formatRelative(key.created_at) }}</td>
            <td class="actions">
              <button v-if="!key.revoked_at" type="button" class="btn btn-ghost btn-sm" :aria-label="`Revoke ${key.name}`" @click="revoke(key)">
                Revoke
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.keys {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.create {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 10px 14px;
  padding: 12px 14px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 0;
  padding: 0;
  border: 0;
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: 550;
}

.field legend {
  margin-bottom: 4px;
  padding: 0;
}

.name {
  flex: 1 1 220px;
}

.scopes {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  min-height: 34px;
  align-items: center;
}

.scope {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text);
  font-size: 13.5px;
  font-weight: 450;
}

.created {
  align-items: flex-start;
}

.created-body {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.secret {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.secret code {
  overflow-wrap: anywhere;
  padding: 4px 8px;
  border-radius: var(--radius-sm);
  background: var(--surface);
  user-select: all;
}

.table-wrap {
  overflow-x: auto;
}

.table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13.5px;
}

.table th,
.table td {
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  text-align: left;
  vertical-align: middle;
}

.table th {
  color: var(--text-3);
  font-size: 12px;
  font-weight: 600;
}

.table tbody tr:last-child td {
  border-bottom: 0;
}

.key-name {
  margin-right: 6px;
  font-weight: 600;
}

.badge {
  margin-left: 6px;
}

.scope-list {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 4px;
}

.revoked td {
  opacity: 0.6;
}

.actions {
  text-align: right;
}

.table-skeleton {
  height: 160px;
  border-radius: var(--radius);
}

@media (max-width: 640px) {
  .hide-sm {
    display: none;
  }
}
</style>
