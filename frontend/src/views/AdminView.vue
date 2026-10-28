<script setup lang="ts">
import { ShieldAlert } from "@lucide/vue";
import { computed, onMounted, ref } from "vue";

import { ApiError, api } from "@/api/client";
import type { Me, TenantUsage } from "@/api/types";
import AdminAudit from "@/components/AdminAudit.vue";
import AdminDomains from "@/components/AdminDomains.vue";
import AdminEvaluations from "@/components/AdminEvaluations.vue";
import AdminKeys from "@/components/AdminKeys.vue";
import AdminMembers from "@/components/AdminMembers.vue";
import PageHeader from "@/components/PageHeader.vue";
import { formatBytes, formatCost, formatNumber } from "@/lib/format";

// The tenant at a glance: this month's usage against its limits, its members,
// domains, API keys, evaluation scores and audit log. Everything but usage needs the admin
// scope: an admin key, or an owner's or admin's sign-in.
const me = ref<Me | null>(null);
const audit = ref<InstanceType<typeof AdminAudit> | null>(null);
const usage = ref<TenantUsage | null>(null);
const error = ref<string | null>(null);

onMounted(async () => {
  try {
    [me.value, usage.value] = await Promise.all([api.me(), api.tenantUsage()]);
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "The tenant could not be loaded.";
  }
});

const isAdmin = computed(() => me.value?.scopes.includes("admin") ?? false);

const signedInAs = computed(() => {
  const m = me.value;
  if (!m) return "";
  if (!m.auth_enabled) return "Authentication is off: every request acts for the default tenant.";
  if (m.user) return `Signed in as ${m.user.name} (${m.user.email}), ${m.role} of this workspace.`;
  return `Signed in with a key with the scopes ${m.scopes.join(", ")}.`;
});

const tiles = computed(() => {
  const u = usage.value;
  if (!u) return [];
  const of = (limit: number | null, format: (n: number) => string) => (limit === null ? "No limit" : `of ${format(limit)}`);
  return [
    { label: "Answers this month", value: formatNumber(u.answers.used), note: of(u.answers.limit, formatNumber), ratio: ratio(u.answers.used, u.answers.limit) },
    { label: "Storage", value: formatBytes(u.storage_bytes.used), note: of(u.storage_bytes.limit, formatBytes), ratio: ratio(u.storage_bytes.used, u.storage_bytes.limit) },
    { label: "Tokens this month", value: formatNumber(u.input_tokens + u.output_tokens), note: `${formatNumber(u.output_tokens)} written by the model`, ratio: null },
    { label: "Cost this month", value: formatCost(u.cost_usd), note: "Answers with a known price", ratio: null },
    {
      label: "Rate limit",
      value: u.requests_per_minute === null ? "None" : formatNumber(u.requests_per_minute),
      note: u.requests_per_minute === null ? "Requests are not limited" : "requests a minute",
      ratio: null,
    },
  ];
});

function ratio(used: number, limit: number | null): number | null {
  return limit ? Math.min(1, used / limit) : null;
}
</script>

<template>
  <div class="page">
    <PageHeader title="Admin" :subtitle="me ? `Workspace ${me.tenant}: usage, members, API keys, evaluation scores and the audit log.` : 'Usage, members, API keys, evaluation scores and the audit log.'">
      <template v-if="me" #meta>
        <p class="subtle small">{{ signedInAs }}</p>
      </template>
    </PageHeader>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>

    <section aria-labelledby="usage-title" class="usage">
      <h2 id="usage-title" class="visually-hidden">Usage</h2>
      <template v-if="!usage && !error">
        <div v-for="i in 5" :key="i" class="skeleton tile-skeleton" />
      </template>
      <div v-for="tile in tiles" :key="tile.label" class="tile card">
        <p class="label">{{ tile.label }}</p>
        <p class="value">{{ tile.value }}</p>
        <p class="subtle small">{{ tile.note }}</p>
        <div v-if="tile.ratio !== null" class="bar" role="progressbar" :aria-label="tile.label" :aria-valuenow="Math.round(tile.ratio * 100)" aria-valuemin="0" aria-valuemax="100">
          <span :class="{ full: tile.ratio >= 1 }" :style="{ width: `${tile.ratio * 100}%` }" />
        </div>
      </div>
    </section>

    <div v-if="me && !isAdmin" class="alert">
      <ShieldAlert :size="18" class="subtle" />
      <span class="muted">Members, API keys, evaluation scores and the audit log need the <strong>admin</strong> scope: an owner's or an admin's role, or a key with it.</span>
    </div>
    <template v-else-if="me">
      <AdminMembers v-if="me.auth_enabled" :my-role="me.role ?? null" :my-user-id="me.user?.id ?? null" @changed="audit?.refresh()" />
      <AdminDomains @changed="audit?.refresh()" />
      <AdminKeys :current-key-id="me.key_id" @changed="audit?.refresh()" />
      <AdminEvaluations />
      <AdminAudit ref="audit" />
    </template>
  </div>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 28px;
  max-width: 1120px;
  margin: 0 auto;
  padding: 28px 32px 48px;
}

@media (max-width: 640px) {
  .page {
    padding: 20px 16px 40px;
  }
}

.usage {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: 12px;
}

.tile {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 14px 16px;
}

.label {
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: 550;
}

.value {
  font-size: 24px;
  font-weight: 650;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
}

.bar {
  height: 5px;
  margin-top: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--surface-2);
}

.bar span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--accent);
}

.bar span.full {
  background: var(--danger);
}

.tile-skeleton {
  height: 100px;
  border-radius: var(--radius);
}
</style>
