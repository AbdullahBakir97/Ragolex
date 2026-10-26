<script setup lang="ts">
import { FlaskConical } from "@lucide/vue";
import { computed, onMounted, ref } from "vue";

import { ApiError, api } from "@/api/client";
import type { EvaluationRun } from "@/api/types";
import { formatDate } from "@/lib/format";

// Retrieval and answer quality over time, from the `ragolex eval` runs recorded
// for the tenant. Runs compare only with runs of the same parameters.
const runs = ref<EvaluationRun[] | null>(null);
const error = ref<string | null>(null);

onMounted(async () => {
  try {
    runs.value = (await api.evaluations({ limit: 100 })).items;
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "The evaluation runs could not be loaded.";
  }
});

const METRICS: { key: string; label: string; answers?: boolean }[] = [
  { key: "hit_rate", label: "Hit rate" },
  { key: "recall", label: "Recall" },
  { key: "mrr", label: "MRR" },
  { key: "correct", label: "Correct answers", answers: true },
  { key: "grounded", label: "Grounded answers", answers: true },
];

function value(run: EvaluationRun, metric: { key: string; answers?: boolean }): number | null {
  const source = metric.answers ? run.answer_metrics : run.metrics;
  return source?.[metric.key] ?? null;
}

function sameSetup(a: EvaluationRun, b: EvaluationRun): boolean {
  return JSON.stringify(a.parameters) === JSON.stringify(b.parameters);
}

/** The latest run of each dataset, the runs it compares with (oldest first), and its tiles. */
const datasets = computed(() => {
  const latest = new Map<string, EvaluationRun>();
  for (const run of runs.value ?? []) if (!latest.has(run.dataset)) latest.set(run.dataset, run);
  return [...latest.values()].map((run) => {
    const comparable = (runs.value ?? []).filter((other) => other.dataset === run.dataset && sameSetup(other, run)).reverse();
    const previous = comparable.length > 1 ? comparable[comparable.length - 2]! : null;
    const tiles = METRICS.filter((metric) => value(run, metric) !== null).map((metric) => {
      const now = value(run, metric)!;
      const before = previous ? value(previous, metric) : null;
      return { ...metric, value: now, change: before === null ? null : now - before };
    });
    const trend = comparable.map((other) => other.metrics.mrr).filter((mrr): mrr is number => mrr !== null);
    return { run, tiles, trend, comparable: comparable.length };
  });
});

function percent(value: number | null): string {
  return value === null ? "—" : `${Math.round(value * 100)}%`;
}

function change(delta: number): string {
  const points = Math.round(delta * 1000) / 10;
  return points === 0 ? "No change" : `${points > 0 ? "+" : "−"}${Math.abs(points)} pts`;
}

/** Points of a sparkline of `values` (0 to 1), 120 × 32. */
function sparkline(values: number[]): string {
  const step = values.length > 1 ? 120 / (values.length - 1) : 0;
  return values.map((v, i) => `${(i * step).toFixed(1)},${(30 - v * 28).toFixed(1)}`).join(" ");
}

function setup(run: EvaluationRun): string {
  const p = run.parameters;
  return [p.embedding_model, p.search_mode, p.reranker ? "reranked" : null, `top ${p.top_k}`, `chunks of ${p.chunk_size}`]
    .filter(Boolean)
    .join(" · ");
}
</script>

<template>
  <section class="evaluations" aria-labelledby="evaluations-title">
    <div>
      <h3 id="evaluations-title">Evaluation</h3>
      <p class="muted small">How well search finds the expected sources, and how good the answers are, run after run.</p>
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-else-if="!runs" class="skeleton tiles-skeleton" />
    <div v-else-if="!runs.length" class="empty card">
      <FlaskConical :size="20" class="subtle" />
      <p class="small">
        No evaluation runs yet. Run <code>ragolex eval evals/handbook/v1</code> on the server; each run's metrics show here.
      </p>
    </div>
    <template v-else>
      <article v-for="entry in datasets" :key="entry.run.id" class="dataset card">
        <header class="dataset-head">
          <div>
            <h4>{{ entry.run.dataset }}<span v-if="entry.run.dataset_version" class="subtle">/{{ entry.run.dataset_version }}</span></h4>
            <p class="subtle small">{{ formatDate(entry.run.created_at) }} · {{ entry.run.cases }} questions · {{ setup(entry.run) }}</p>
          </div>
          <figure v-if="entry.trend.length > 1" class="trend">
            <svg viewBox="0 0 120 32" width="120" height="32" role="img" :aria-label="`MRR over the last ${entry.trend.length} comparable runs`">
              <polyline :points="sparkline(entry.trend)" fill="none" stroke-width="2" />
            </svg>
            <figcaption class="subtle small">MRR, {{ entry.trend.length }} runs</figcaption>
          </figure>
        </header>
        <div class="tiles">
          <div v-for="tile in entry.tiles" :key="tile.key" class="tile">
            <p class="label">{{ tile.label }}</p>
            <p class="value">{{ percent(tile.value) }}</p>
            <p v-if="tile.change !== null" class="small" :class="tile.change > 0 ? 'up' : tile.change < 0 ? 'down' : 'subtle'">
              {{ change(tile.change) }}
            </p>
            <p v-else class="subtle small">First run of this setup</p>
          </div>
        </div>
      </article>

      <div class="table-wrap card">
        <table class="table">
          <caption class="visually-hidden">Evaluation runs, most recent first</caption>
          <thead>
            <tr>
              <th scope="col">Run</th>
              <th scope="col">Dataset</th>
              <th scope="col" class="hide-sm">Setup</th>
              <th scope="col" class="number">Hit rate</th>
              <th scope="col" class="number">Recall</th>
              <th scope="col" class="number">MRR</th>
              <th scope="col" class="number hide-sm">Correct</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="run in runs" :key="run.id">
              <td class="small">{{ formatDate(run.created_at) }}</td>
              <td>{{ run.dataset }}<span v-if="run.dataset_version" class="subtle">/{{ run.dataset_version }}</span></td>
              <td class="hide-sm subtle small">{{ setup(run) }}</td>
              <td class="number">{{ percent(run.metrics.hit_rate ?? null) }}</td>
              <td class="number">{{ percent(run.metrics.recall ?? null) }}</td>
              <td class="number">{{ percent(run.metrics.mrr ?? null) }}</td>
              <td class="number hide-sm">{{ percent(run.answer_metrics?.correct ?? null) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>

<style scoped>
.evaluations {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.empty {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
}

.dataset {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px 16px;
}

.dataset-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.trend {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  margin: 0;
}

.trend polyline {
  stroke: var(--accent);
  stroke-linejoin: round;
  stroke-linecap: round;
}

.tiles {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 10px;
}

.tile {
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--surface-2);
}

.label {
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: 550;
}

.value {
  font-size: 22px;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
}

.up {
  color: var(--success);
}

.down {
  color: var(--danger);
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
}

.table th {
  color: var(--text-3);
  font-size: 12px;
  font-weight: 600;
}

.table tbody tr:last-child td {
  border-bottom: 0;
}

.number {
  text-align: right !important;
  font-variant-numeric: tabular-nums;
}

.tiles-skeleton {
  height: 160px;
  border-radius: var(--radius);
}

@media (max-width: 640px) {
  .hide-sm {
    display: none;
  }
}
</style>
