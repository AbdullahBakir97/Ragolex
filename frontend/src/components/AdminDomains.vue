<script setup lang="ts">
import { Check, Copy, Globe, LoaderCircle, Plus } from "@lucide/vue";
import { onMounted, ref } from "vue";

import { ApiError, api } from "@/api/client";
import type { Domain } from "@/api/types";
import { useToasts } from "@/composables/useToasts";
import { formatRelative } from "@/lib/format";

// The workspace's own domains: added, proven with a TXT record, removed.
const emit = defineEmits<{ changed: [] }>();

const toasts = useToasts();
const domains = ref<Domain[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);
const name = ref("");
const adding = ref(false);
const checking = ref<string | null>(null);
const copied = ref<string | null>(null);

const message = (caught: unknown) => (caught instanceof ApiError ? caught.message : undefined);

async function load() {
  try {
    domains.value = await api.domains();
    error.value = null;
  } catch (caught) {
    error.value = message(caught) ?? "The domains could not be loaded.";
  } finally {
    loading.value = false;
  }
}
onMounted(load);

async function add() {
  // People paste addresses: keep the host name.
  const domain = name.value.trim().replace(/^https?:\/\//i, "").replace(/[/?#].*$/, "");
  if (!domain || adding.value) return;
  adding.value = true;
  try {
    await api.addDomain(domain);
    name.value = "";
    emit("changed");
    await load();
  } catch (caught) {
    toasts.error("The domain could not be added", message(caught));
  } finally {
    adding.value = false;
  }
}

async function verify(domain: Domain) {
  checking.value = domain.id;
  try {
    await api.verifyDomain(domain.id);
    toasts.success("Domain verified", `${domain.domain} serves this workspace now.`);
    emit("changed");
  } catch (caught) {
    toasts.error(`${domain.domain} is not verified yet`, message(caught));
  } finally {
    checking.value = null;
    await load();
  }
}

async function remove(domain: Domain) {
  if (!window.confirm(`Remove ${domain.domain}? It stops serving this workspace at once.`)) return;
  try {
    await api.removeDomain(domain.id);
    toasts.success("Domain removed", `${domain.domain} no longer serves this workspace.`);
    emit("changed");
    await load();
  } catch (caught) {
    toasts.error("The domain could not be removed", message(caught));
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
  <section class="domains" aria-labelledby="domains-title">
    <div>
      <h3 id="domains-title">Domains</h3>
      <p class="muted small">
        Serve this workspace on a domain of its own, such as help.example.com: its sign-in, projects and chat widgets.
        Add the two DNS records shown, then check: once the TXT record is found, the domain is verified.
      </p>
    </div>

    <form class="add card" @submit.prevent="add">
      <label class="field domain">
        <span>Domain</span>
        <input v-model="name" class="input" maxlength="253" placeholder="help.example.com" required />
      </label>
      <button type="submit" class="btn btn-primary" :disabled="adding || !name.trim()">
        <Plus :size="15" /> Add domain
      </button>
    </form>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-else-if="loading" class="skeleton list-skeleton" />
    <p v-else-if="!domains.length" class="subtle small">No domains yet: the workspace is served on this server's address.</p>
    <article v-for="domain in domains" :key="domain.id" class="domain-card card" :aria-label="domain.domain">
      <header class="domain-head">
        <Globe :size="16" class="subtle" />
        <strong class="domain-name">{{ domain.domain }}</strong>
        <span v-if="domain.verified" class="badge badge-success">Verified</span>
        <span v-else class="badge badge-warning">Waiting for its TXT record</span>
        <span class="actions">
          <button
            v-if="!domain.verified"
            type="button"
            class="btn btn-sm"
            :disabled="checking === domain.id"
            @click="verify(domain)"
          >
            <LoaderCircle v-if="checking === domain.id" :size="14" class="spin" /> Check now
          </button>
          <button type="button" class="btn btn-ghost btn-sm" :aria-label="`Remove ${domain.domain}`" @click="remove(domain)">
            Remove
          </button>
        </span>
      </header>
      <p v-if="domain.verified" class="subtle small">
        Verified {{ formatRelative(domain.verified_at!) }}. Keep its CNAME pointing here.
      </p>
      <p v-else class="subtle small">
        {{ domain.checked_at ? `Last checked ${formatRelative(domain.checked_at)}.` : "Not checked yet." }}
        Add these records at the domain's DNS provider:
      </p>
      <div class="table-wrap">
        <table class="table">
          <caption class="visually-hidden">DNS records for {{ domain.domain }}</caption>
          <thead>
            <tr>
              <th scope="col">Type</th>
              <th scope="col">Name</th>
              <th scope="col">Value</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="record in domain.records" :key="record.type">
              <td><span class="chip">{{ record.type }}</span></td>
              <td class="mono">{{ record.name }}</td>
              <td>
                <span class="value">
                  <code class="mono">{{ record.value }}</code>
                  <button
                    type="button"
                    class="btn btn-ghost btn-icon btn-sm"
                    :aria-label="`Copy the ${record.type} value for ${domain.domain}`"
                    @click="copy(record.value)"
                  >
                    <component :is="copied === record.value ? Check : Copy" :size="14" />
                  </button>
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </article>
  </section>
</template>

<style scoped>
.domains {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.add {
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
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: 550;
}

.domain {
  flex: 1 1 240px;
}

.domain-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px;
}

.domain-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.domain-name {
  overflow-wrap: anywhere;
}

.actions {
  display: flex;
  gap: 6px;
  margin-left: auto;
}

.table-wrap {
  overflow-x: auto;
}

.table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.table th,
.table td {
  padding: 6px 8px;
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

.value {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.value code {
  overflow-wrap: anywhere;
}

.list-skeleton {
  height: 120px;
  border-radius: var(--radius);
}
</style>
