<script setup lang="ts">
import { Check, Copy, LoaderCircle, TriangleAlert } from "@lucide/vue";
import { computed, onMounted, reactive, ref } from "vue";

import { ApiError, api } from "@/api/client";
import type { SsoProtocol, SsoRole, SsoSettings } from "@/api/types";
import { useToasts } from "@/composables/useToasts";
import { formatRelative } from "@/lib/format";

// Single sign-on: the workspace's identity provider, through OpenID Connect or SAML 2.0. People
// whose email is on one of the workspace's verified domains sign in through it.
const props = defineProps<{ myRole: string | null }>();
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
const copied = ref<string | null>(null);
const form = reactive({
  protocol: "oidc" as SsoProtocol,
  issuer: "",
  client_id: "",
  client_secret: "",
  sso_url: "",
  certificate: "",
  default_role: "viewer" as SsoRole,
  enabled: true,
  required: false,
});
// The saved provider speaks the protocol chosen: its secret or certificate may be left out.
const keeps = computed(() => settings.value?.provider?.protocol === form.protocol);

const message = (caught: unknown) => (caught instanceof ApiError ? caught.message : undefined);

function fill(loaded: SsoSettings) {
  settings.value = loaded;
  const provider = loaded.provider;
  form.protocol = provider?.protocol ?? "oidc";
  form.issuer = provider?.issuer ?? "";
  form.client_id = provider?.client_id ?? "";
  form.client_secret = "";
  form.sso_url = provider?.sso_url ?? "";
  form.certificate = "";
  form.default_role = provider?.default_role ?? "viewer";
  form.enabled = provider?.enabled ?? true;
  form.required = provider?.required ?? false;
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
    const certificate = form.certificate.trim();
    const common = { issuer: form.issuer.trim(), default_role: form.default_role, enabled: form.enabled, required: form.required };
    fill(
      await api.saveSso(
        form.protocol === "saml"
          ? { protocol: "saml", ...common, sso_url: form.sso_url.trim(), ...(certificate ? { certificate } : {}) }
          : { protocol: "oidc", ...common, client_id: form.client_id.trim(), ...(secret ? { client_secret: secret } : {}) },
      ),
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
    copied.value = text;
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
        Let people sign in with their organisation's account (Microsoft Entra ID, Google Workspace, Okta, Keycloak, AD FS
        or any OpenID Connect or SAML 2.0 provider). Their first sign-in makes their account, or adds it to this workspace,
        with the role below.
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
        <fieldset class="field wide protocol">
          <legend>Protocol</legend>
          <label class="check small"><input v-model="form.protocol" type="radio" value="oidc" /> OpenID Connect</label>
          <label class="check small"><input v-model="form.protocol" type="radio" value="saml" /> SAML 2.0</label>
        </fieldset>
        <template v-if="form.protocol === 'oidc'">
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
              :required="!keeps"
              :placeholder="keeps ? 'Saved; leave empty to keep it' : ''"
            />
          </label>
        </template>
        <template v-else>
          <label class="field wide">
            <span>Identity provider entity ID (issuer)</span>
            <input v-model="form.issuer" class="input mono saml-entity" required maxlength="500" placeholder="https://sts.windows.net/<tenant>/" />
          </label>
          <label class="field wide">
            <span>Sign-in URL (single sign-on service)</span>
            <input
              v-model="form.sso_url"
              class="input mono saml-url"
              type="url"
              required
              maxlength="2000"
              placeholder="https://login.microsoftonline.com/<tenant>/saml2"
            />
          </label>
          <label class="field wide">
            <span>Signing certificate (PEM or base64)</span>
            <textarea
              v-model="form.certificate"
              class="input mono certificate"
              rows="4"
              maxlength="20000"
              :required="!keeps"
              :placeholder="keeps ? 'Saved; leave empty to keep it' : '-----BEGIN CERTIFICATE-----'"
            />
            <span v-if="keeps && settings.provider?.certificate_expires_at" class="subtle small hint">
              The saved certificate expires {{ formatRelative(settings.provider.certificate_expires_at) }}.
            </span>
          </label>
        </template>
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
          <label class="check small">
            <input v-model="form.required" type="checkbox" :disabled="props.myRole !== 'owner' || !settings.email_domains.length" />
            Require it: members sign in only through the provider, not with a password, and join through it, not by invitation
          </label>
          <span class="subtle small hint">
            {{ props.myRole === "owner"
              ? "Owners keep their passwords, so a broken provider cannot lock you out. Members signed in with a password are signed out."
              : "Only an owner turns this on or off." }}
          </span>
        </div>
        <div v-if="form.protocol === 'oidc'" class="field wide">
          <span>Redirect URI to register with the provider</span>
          <span class="value">
            <code class="mono">{{ settings.redirect_uri }}</code>
            <button type="button" class="btn btn-ghost btn-icon btn-sm" aria-label="Copy the redirect URI" @click="copy(settings.redirect_uri)">
              <component :is="copied === settings.redirect_uri ? Check : Copy" :size="14" />
            </button>
          </span>
        </div>
        <template v-else>
          <div class="field wide">
            <span>Entity ID (audience) and metadata URL to give the provider</span>
            <span class="value">
              <code class="mono">{{ settings.saml_entity_id }}</code>
              <button type="button" class="btn btn-ghost btn-icon btn-sm" aria-label="Copy the entity ID" @click="copy(settings.saml_entity_id)">
                <component :is="copied === settings.saml_entity_id ? Check : Copy" :size="14" />
              </button>
            </span>
          </div>
          <div class="field wide">
            <span>Reply URL (assertion consumer service)</span>
            <span class="value">
              <code class="mono">{{ settings.saml_acs_url }}</code>
              <button type="button" class="btn btn-ghost btn-icon btn-sm" aria-label="Copy the reply URL" @click="copy(settings.saml_acs_url)">
                <component :is="copied === settings.saml_acs_url ? Check : Copy" :size="14" />
              </button>
            </span>
          </div>
        </template>
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

.protocol {
  flex-direction: row;
  flex-wrap: wrap;
  gap: 4px 16px;
  margin: 0;
  padding: 0;
  border: 0;
}

.protocol legend {
  width: 100%;
  margin-bottom: 4px;
}

.certificate {
  resize: vertical;
  font-size: 12px;
}

.hint {
  font-weight: 400;
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
