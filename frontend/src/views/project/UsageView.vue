<script setup lang="ts">
import { Info } from "@lucide/vue";
import { computed, onMounted, ref, watch } from "vue";

import { ApiError, api } from "@/api/client";
import type { ProjectUsage, TenantUsage } from "@/api/types";
import CostHistory from "@/components/CostHistory.vue";
import FeedbackList from "@/components/FeedbackList.vue";
import { useProject } from "@/composables/useProject";
import { formatBytes, formatCost, formatNumber, formatPercent } from "@/lib/format";

const { name } = useProject();
const usage = ref<ProjectUsage | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);

async function load() {
  loading.value = true;
  try {
    usage.value = await api.usage(name.value);
    error.value = null;
  } catch (caught) {
    const empty = caught instanceof ApiError && caught.signal === "project_not_found";
    usage.value = empty
      ? { answers: 0, answered: 0, input_tokens: 0, output_tokens: 0, cost_usd: 0, unpriced_answers: 0 }
      : null;
    error.value = empty ? null : caught instanceof ApiError ? caught.message : "Usage could not be loaded.";
  } finally {
    loading.value = false;
  }
}

const cards = computed(() => {
  const u = usage.value;
  if (!u) return [];
  return [
    { label: "Questions", value: formatNumber(u.answers), note: "Streamed or not" },
    {
      label: "Answered",
      value: formatPercent(u.answered, u.answers),
      note: `${formatNumber(u.answered)} answered, ${formatNumber(u.answers - u.answered)} not in the documents`,
    },
    { label: "Input tokens", value: formatNumber(u.input_tokens), note: "Prompts with their sources" },
    { label: "Output tokens", value: formatNumber(u.output_tokens), note: "Written by the model" },
    {
      label: "Cost",
      value: formatCost(u.cost_usd),
      note: u.answers ? `${formatCost(u.cost_usd / Math.max(1, u.answers - u.unpriced_answers))} per priced answer` : "US dollars",
    },
  ];
});

// The tenant's quotas, across all its projects; shown when it has any.
const tenant = ref<TenantUsage | null>(null);
const meters = computed(() => {
  const t = tenant.value;
  if (!t) return [];
  return [
    {
      label: "Answers this month",
      used: t.answers.used,
      limit: t.answers.limit,
      format: formatNumber,
      full: "Questions are refused until the month ends.",
    },
    {
      label: "Storage",
      used: t.storage_bytes.used,
      limit: t.storage_bytes.limit,
      format: formatBytes,
      full: "Uploads are refused until files are deleted.",
    },
    {
      label: "Budget this month",
      used: t.cost_usd,
      limit: t.budget_usd,
      format: formatCost,
      full: "The budget is spent: questions are refused until the month ends.",
    },
  ].filter((meter) => meter.limit !== null);
});

watch(name, load);
onMounted(async () => {
  await load();
  tenant.value = await api.tenantUsage().catch(() => null);
});
</script>

<template>
  <section class="usage">
    <div>
      <h2>Usage</h2>
      <p class="muted small">Tokens and cost of every answer in this project, and what people thought of them.</p>
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>

    <div class="grid">
      <template v-if="loading">
        <div v-for="i in 5" :key="i" class="skeleton stat-skeleton" />
      </template>
      <div v-for="card in cards" v-else :key="card.label" class="stat card">
        <p class="label">{{ card.label }}</p>
        <p class="value">{{ card.value }}</p>
        <p class="subtle small">{{ card.note }}</p>
      </div>
    </div>

    <div v-if="usage && usage.unpriced_answers > 0" class="alert">
      <Info :size="18" class="subtle" />
      <span class="muted">
        {{ formatNumber(usage.unpriced_answers) }}
        {{ usage.unpriced_answers === 1 ? "answer has" : "answers have" }} no known cost and
        {{ usage.unpriced_answers === 1 ? "is" : "are" }} not in the total. Set
        <code>LLM_INPUT_PRICE_PER_MILLION</code> and <code>LLM_OUTPUT_PRICE_PER_MILLION</code> on the server to
        price answers.
      </span>
    </div>

    <div v-if="meters.length || tenant?.requests_per_minute" class="quotas card">
      <h3>Limits of {{ tenant?.tenant }}</h3>
      <p class="muted small">Across all of its projects. The month started on {{ tenant ? new Date(tenant.period_start).toLocaleDateString() : "" }}.</p>
      <div v-for="meter in meters" :key="meter.label" class="meter">
        <div class="meter-line">
          <span>{{ meter.label }}</span>
          <span class="subtle small">{{ meter.format(meter.used) }} of {{ meter.format(meter.limit!) }}</span>
        </div>
        <div class="bar" role="progressbar" :aria-label="meter.label" :aria-valuenow="Math.round((meter.used / meter.limit!) * 100)" aria-valuemin="0" aria-valuemax="100">
          <span :class="{ full: meter.used >= meter.limit! }" :style="{ width: `${Math.min(100, (meter.used / meter.limit!) * 100)}%` }" />
        </div>
        <p v-if="meter.used >= meter.limit!" class="full-note small">{{ meter.full }}</p>
      </div>
      <p v-if="tenant?.requests_per_minute" class="subtle small">Up to {{ formatNumber(tenant.requests_per_minute) }} requests a minute.</p>
    </div>

    <CostHistory :project="name" />

    <FeedbackList :project="name" class="feedback-section" />
  </section>
</template>

<style scoped>
.usage {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: 12px;
}

.stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 16px;
}

.label {
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: 550;
}

.value {
  font-size: 26px;
  font-weight: 650;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
}

.quotas {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px;
}

.meter-line {
  display: flex;
  justify-content: space-between;
  margin-bottom: 4px;
  font-size: 13.5px;
}

.bar {
  height: 6px;
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

.full-note {
  margin-top: 4px;
  color: var(--danger);
}

.feedback-section {
  margin-top: 14px;
}

.stat-skeleton {
  height: 104px;
  border-radius: var(--radius);
}
</style>
