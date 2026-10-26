<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import { ApiError, api } from "@/api/client";
import type { UsageHistory } from "@/api/types";
import { formatCost, formatNumber } from "@/lib/format";

// The tenant's spending over a period, across all its projects: a chart per
// day, and what each project and model cost.
const props = defineProps<{ project?: string }>();

const PERIODS = [7, 30, 90] as const;
const days = ref<(typeof PERIODS)[number]>(30);
const metric = ref<"cost" | "answers">("cost");
const history = ref<UsageHistory | null>(null);
const error = ref<string | null>(null);

async function load() {
  try {
    history.value = await api.usageHistory(days.value);
    error.value = null;
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "The cost history could not be loaded.";
  }
}

const totals = computed(() => {
  const all = history.value?.days ?? [];
  const cost = all.reduce((sum, day) => sum + day.cost_usd, 0);
  const answers = all.reduce((sum, day) => sum + day.answers, 0);
  return { cost, answers, perDay: all.length ? cost / all.length : 0 };
});

// One bar per day, as a share of the period's highest day.
const WIDTH = 600;
const HEIGHT = 120;
const bars = computed(() => {
  const all = history.value?.days ?? [];
  const value = (day: UsageHistory["days"][number]) => (metric.value === "cost" ? day.cost_usd : day.answers);
  const highest = Math.max(0, ...all.map(value));
  const slot = WIDTH / Math.max(1, all.length);
  return all.map((day, index) => {
    const height = highest ? Math.max(value(day) ? 2 : 0, (value(day) / highest) * HEIGHT) : 0;
    return {
      day: day.day,
      x: index * slot + slot * 0.15,
      width: slot * 0.7,
      y: HEIGHT - height,
      height,
      label: `${formatDay(day.day)}: ${formatCost(day.cost_usd)}, ${formatNumber(day.answers)} ${day.answers === 1 ? "answer" : "answers"}`,
    };
  });
});

const summary = computed(() => {
  const label = metric.value === "cost" ? `${formatCost(totals.value.cost)} spent` : `${formatNumber(totals.value.answers)} answers`;
  return `${metric.value === "cost" ? "Cost" : "Answers"} per day over the last ${days.value} days: ${label} in all.`;
});

const dayFormat = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" });

function formatDay(day: string): string {
  return dayFormat.format(new Date(`${day}T00:00:00Z`));
}

watch(days, load);
onMounted(load);
</script>

<template>
  <section class="history card" aria-labelledby="cost-history-title">
    <div class="head">
      <div>
        <h3 id="cost-history-title">Spending</h3>
        <p class="muted small">Answers of every project of the tenant, per day (UTC).</p>
      </div>
      <div class="controls">
        <div class="segmented" role="group" aria-label="Show">
          <button type="button" :aria-pressed="metric === 'cost'" @click="metric = 'cost'">Cost</button>
          <button type="button" :aria-pressed="metric === 'answers'" @click="metric = 'answers'">Answers</button>
        </div>
        <label class="visually-hidden" for="cost-history-days">Period</label>
        <select id="cost-history-days" v-model.number="days" class="select period">
          <option v-for="period in PERIODS" :key="period" :value="period">Last {{ period }} days</option>
        </select>
      </div>
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-else-if="!history" class="skeleton chart-skeleton" />
    <template v-else>
      <div class="figures">
        <p><span class="figure">{{ formatCost(totals.cost) }}</span> <span class="subtle small">spent</span></p>
        <p><span class="figure">{{ formatNumber(totals.answers) }}</span> <span class="subtle small">answers</span></p>
        <p><span class="figure">{{ formatCost(totals.perDay) }}</span> <span class="subtle small">a day on average</span></p>
      </div>

      <svg class="chart" :viewBox="`0 0 ${WIDTH} ${HEIGHT}`" preserveAspectRatio="none" role="img" :aria-label="summary">
        <line class="baseline" x1="0" :y1="HEIGHT - 0.5" :x2="WIDTH" :y2="HEIGHT - 0.5" />
        <rect v-for="bar in bars" :key="bar.day" :x="bar.x" :y="bar.y" :width="bar.width" :height="bar.height" rx="1.5">
          <title>{{ bar.label }}</title>
        </rect>
      </svg>
      <div class="axis subtle small" aria-hidden="true">
        <span>{{ formatDay(history.days[0]!.day) }}</span>
        <span>{{ formatDay(history.days[history.days.length - 1]!.day) }}</span>
      </div>

      <div v-if="history.projects.length" class="shares">
        <table class="table">
          <caption class="visually-hidden">Cost per project</caption>
          <thead>
            <tr>
              <th scope="col">Project</th>
              <th scope="col" class="number">Answers</th>
              <th scope="col" class="number">Cost</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="share in history.projects" :key="share.project" :class="{ current: share.project === props.project }">
              <td>{{ share.project }}</td>
              <td class="number">{{ formatNumber(share.answers) }}</td>
              <td class="number">{{ formatCost(share.cost_usd) }}</td>
            </tr>
          </tbody>
        </table>
        <table class="table">
          <caption class="visually-hidden">Cost per model</caption>
          <thead>
            <tr>
              <th scope="col">Model</th>
              <th scope="col" class="number">Tokens</th>
              <th scope="col" class="number">Cost</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="share in history.models" :key="share.model ?? ''">
              <td :class="{ subtle: !share.model }">{{ share.model ?? "No model called" }}</td>
              <td class="number">{{ formatNumber(share.input_tokens + share.output_tokens) }}</td>
              <td class="number">{{ formatCost(share.cost_usd) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="subtle small">No answers in this period.</p>
    </template>
  </section>
</template>

<style scoped>
.history {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
}

.head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.controls {
  display: flex;
  gap: 8px;
}

.period {
  width: auto;
}

.segmented {
  display: inline-flex;
  overflow: hidden;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
}

.segmented button {
  padding: 0 12px;
  border: 0;
  background: var(--surface);
  color: var(--text-2);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}

.segmented button + button {
  border-left: 1px solid var(--border-strong);
}

.segmented button[aria-pressed="true"] {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
}

.segmented button:focus-visible {
  box-shadow: var(--focus);
  outline: none;
}

.figures {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 24px;
}

.figure {
  font-size: 20px;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
}

.chart {
  width: 100%;
  height: 140px;
}

.chart rect {
  fill: var(--accent);
}

.chart rect:hover {
  fill: var(--accent-hover);
}

.baseline {
  stroke: var(--border);
}

.axis {
  display: flex;
  justify-content: space-between;
  margin-top: -6px;
}

.shares {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 16px;
}

.table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13.5px;
}

.table th,
.table td {
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
  text-align: left;
}

.table th {
  color: var(--text-3);
  font-size: 12px;
  font-weight: 600;
}

.table tbody tr:last-child td {
  border-bottom: 0;
}

.table .number {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.current td:first-child {
  font-weight: 600;
}

.chart-skeleton {
  height: 200px;
  border-radius: var(--radius);
}
</style>
