<script setup lang="ts">
import { Check, Copy, LoaderCircle, TriangleAlert } from "@lucide/vue";
import { onMounted, reactive, ref } from "vue";

import { ApiError, api } from "@/api/client";
import type { SsoRole, SsoSettings } from "@/api/types";
import { useToasts } from "@/composables/useToasts";
import { formatRelative } from "@/lib/format";

// Single sign-on: the workspace's OpenID Connect identity provider. People whose email is on
// one of the workspace's verified domains sign in through it.
const emit = defineEmits<{ changed: [] }>();

const ROLES: { role: SsoRole; label: string }[] = [
  { role: "viewer", label: "viewer – Read and ask" },
  { role: "editor", label: "editor – Upload, change and ask" },
  { role: "admin", label: "admin – Everything but owners" },
];

const toasts = useToasts();
const settings = ref<SsoSettings | null>(null);
const error = ref<string | null>(null);
const saving = ref(false);
const copied = ref(false);
const form = reactive({ issuer: "", client_id: "", client_secret: "", default_role: "viewer" as SsoRole, enabled: true });

const message = (caught: unknown) => (caught instanceof ApiError ? caught.message : undefined);

function fill(loaded: SsoSettings) {
  settings.value = loaded;
  const provider = loaded.provider;
  form.issuer = provider?.issuer ?? "";
  form.client_id = provider?.client_id ?? "";
  form.client_secret = "";
  form.default_role = provider?.default_role ?? "viewer";
  form.enabled = provider?.enabled ?? true;
}

async function load() {
  try {
    fill(await api.sso());
    error.value = null;
  } catch (caught) {
    error.value = message(caught) ?? "Single sign-on could not be loaded.";
  }
}
onMounted(load);

async function save() {
  if (saving.value) return;
  saving.value = true;
  try {
    const secret = form.client_secret.trim();
    fill(
      await api.saveSso({
        issuer: form.issuer.trim(),
        client_id: form.client_id.trim(),
        ...(secret ? { client_secret: secret } : {}),
        default_role: form.default_role,
        enabled: form.enabled,
      }),
    );
    toasts.success("Single sign-on saved", form.enabled ? "People can sign in through it now." : "It is turned off.");
    emit("changed");
  } catch (caught) {
    toasts.error("Single sign-on could not be saved", message(caught));
  } finally {
    saving.value = false;
  }
}

async function remove() {
  if (!window.confirm("Remove single sign-on? Accounts it made stay, and can set a password with a reset link.")) return;
  try {
    await api.deleteSso();
    toasts.success("Single sign-on removed");
    emit("changed");
    await load();
  } catch (caught) {
    toasts.error("Single sign-on could not be removed", message(caught));
  }
}

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    copied.value = true;
  } catch {
    toasts.error("Copying failed", "Select the text and copy it by hand.");
  }
}
</script>

<template>
  <section class="sso" aria-labelledby="sso-title">
    <div>
      <h3 id="sso-title">Single sign-on</h3>
      <p class="muted small">
        Let people sign in with their organisation's account (Microsoft Entra ID, Google Workspace, Okta, Keycloak or any
        OpenID Connect provider). Their first sign-in makes their account, or adds it to this workspace, with the role below.
      </p>
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-else-if="!settings" class="skeleton form-skeleton" />
    <template v-else>
      <p v-if="!settings.email_domains.length" class="alert alert-warning small" role="status">
        <TriangleAlert :size="15" aria-hidden="true" />
        Add your organisation's email domain (such as acme.com) under Domains and verify it first: only emails on the
        workspace's verified domains sign in through its provider.
      </p>
      <p v-else class="subtle small">
        Emails on {{ settings.email_domains.join(", ") }} sign in through it.
      </p>

      <form class="card form" @submit.prevent="save">
        <label class="field wide">
          <span>Issuer URL</span>
          <input
            v-model="form.issuer"
            class="input mono"
            type="url"
            required
            maxlength="500"
            placeholder="https://login.microsoftonline.com/<tenant>/v2.0"
          />
        </label>
        <label class="field">
          <span>Client ID</span>
          <input v-model="form.client_id" class="input mono" required maxlength="255" autocomplete="off" />
        </label>
        <label class="field">
          <span>Client secret</span>
          <input
            v-model="form.client_secret"
            class="input mono"
            type="password"
            maxlength="1000"
            autocomplete="off"
            :required="!settings.provider"
            :placeholder="settings.provider ? 'Saved; leave empty to keep it' : ''"
          />
        </label>
        <label class="field">
          <span>Role of new members</span>
          <select v-model="form.default_role" class="input">
            <option v-for="option in ROLES" :key="option.role" :value="option.role">{{ option.label }}</option>
          </select>
        </label>
        <label class="check small">
          <input v-model="form.enabled" type="checkbox" /> Turned on
        </label>
        <div class="field wide">
          <span>Redirect URI to register with the provider</span>
          <span class="value">
            <code class="mono">{{ settings.redirect_uri }}</code>
            <button type="button" class="btn btn-ghost btn-icon btn-sm" aria-label="Copy the redirect URI" @click="copy(settings.redirect_uri)">
              <component :is="copied ? Check : Copy" :size="14" />
            </button>
          </span>
        </div>
        <div class="actions wide">
          <span v-if="settings.provider" class="subtle small">Saved {{ formatRelative(settings.provider.updated_at) }}</span>
          <button v-if="settings.provider" type="button" class="btn btn-ghost" @click="remove">Remove</button>
          <button type="submit" class="btn btn-primary" :disabled="saving">
            <LoaderCircle v-if="saving" :size="15" class="spin" /> Save
          </button>
        </div>
      </form>
    </template>
  </section>
</template>

<style scoped>
.sso {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.form {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px 14px;
  padding: 14px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: 550;
}

.wide {
  grid-column: 1 / -1;
}

.check {
  display: flex;
  align-items: center;
  gap: 6px;
  align-self: end;
  padding-bottom: 8px;
}

.value {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  font-weight: 400;
}

.value code {
  overflow-wrap: anywhere;
}

.actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
}

.alert-warning {
  display: flex;
  align-items: flex-start;
  gap: 6px;
}

.form-skeleton {
  height: 160px;
  border-radius: var(--radius);
}
</style>
