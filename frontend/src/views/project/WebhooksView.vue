<script setup lang="ts">
import { Check, ChevronDown, ChevronRight, Copy, LoaderCircle, Plus, RefreshCw, Send, Trash2, Webhook as WebhookIcon } from "@lucide/vue";
import { onMounted, ref, watch } from "vue";

import { ApiError, api } from "@/api/client";
import type { CreatedWebhook, Page, Webhook, WebhookDelivery, WebhookEvent } from "@/api/types";
import { WEBHOOK_EVENTS } from "@/api/types";
import PagerControls from "@/components/PagerControls.vue";
import { useProject } from "@/composables/useProject";
import { useProjects } from "@/composables/useProjects";
import { useToasts } from "@/composables/useToasts";
import { formatRelative } from "@/lib/format";

const { name, refresh: refreshProject } = useProject();
const { refresh: refreshProjects } = useProjects();
const toasts = useToasts();

const EVENT_HELP: Record<WebhookEvent, string> = {
  "file.uploaded": "A file was uploaded (not when its content was there already)",
  "file.deleted": "A file was deleted with its chunks",
  "job.succeeded": "A file was processed and indexed",
  "job.failed": "Processing a file failed, after its last attempt",
  "source.synced": "A website source was synced: pages added, updated and removed",
  "budget.alert": "The tenant's answers reached 80% or 100% of its monthly budget",
};

const webhooks = ref<Webhook[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);

async function load() {
  loading.value = true;
  try {
    webhooks.value = (await api.webhooks(name.value)).items;
    error.value = null;
  } catch (caught) {
    const empty = caught instanceof ApiError && caught.signal === "project_not_found";
    webhooks.value = [];
    error.value = empty ? null : caught instanceof ApiError ? caught.message : "Webhooks could not be loaded.";
  } finally {
    loading.value = false;
  }
}

// Adding one.
const url = ref("");
const description = ref("");
const events = ref<WebhookEvent[]>(["job.succeeded", "job.failed"]);
const creating = ref(false);
const created = ref<CreatedWebhook | null>(null);
const copied = ref(false);

async function create() {
  creating.value = true;
  try {
    created.value = await api.createWebhook(name.value, {
      url: url.value.trim(),
      events: events.value,
      description: description.value.trim() || null,
    });
    copied.value = false;
    url.value = "";
    description.value = "";
    await load();
    // Adding a webhook creates the project if it had no files yet.
    await Promise.all([refreshProject(), refreshProjects()]);
  } catch (caught) {
    toasts.error("The webhook could not be added", caught instanceof ApiError ? caught.message : undefined);
  } finally {
    creating.value = false;
  }
}

async function copySecret() {
  if (!created.value) return;
  try {
    await navigator.clipboard.writeText(created.value.secret);
    copied.value = true;
  } catch {
    toasts.error("Copying failed", "Select the secret and copy it by hand.");
  }
}

// Each webhook's actions and deliveries.
const confirmingDelete = ref<string | null>(null);
const busy = ref<string | null>(null);
const open = ref<string | null>(null);
const deliveries = ref<Page<WebhookDelivery> | null>(null);
const loadingDeliveries = ref(false);

async function remove(webhook: Webhook) {
  busy.value = webhook.id;
  try {
    await api.deleteWebhook(name.value, webhook.id);
    toasts.success("Webhook deleted", `Events no longer go to ${webhook.url}.`);
    if (open.value === webhook.id) open.value = null;
    if (created.value?.id === webhook.id) created.value = null;
    await load();
  } catch (caught) {
    toasts.error("The webhook could not be deleted", caught instanceof ApiError ? caught.message : undefined);
  } finally {
    busy.value = null;
    confirmingDelete.value = null;
  }
}

async function ping(webhook: Webhook) {
  busy.value = webhook.id;
  try {
    await api.pingWebhook(name.value, webhook.id);
    toasts.success("Ping queued", "It is sent within a few seconds; its outcome shows under Deliveries.");
    open.value = webhook.id;
    await loadDeliveries(0);
  } catch (caught) {
    toasts.error("The ping could not be queued", caught instanceof ApiError ? caught.message : undefined);
  } finally {
    busy.value = null;
  }
}

async function toggle(webhook: Webhook) {
  open.value = open.value === webhook.id ? null : webhook.id;
  deliveries.value = null;
  if (open.value) await loadDeliveries(0);
}

async function loadDeliveries(offset: number) {
  if (!open.value) return;
  loadingDeliveries.value = true;
  try {
    deliveries.value = await api.deliveries(name.value, open.value, { offset, limit: 10 });
  } catch (caught) {
    toasts.error("Deliveries could not be loaded", caught instanceof ApiError ? caught.message : undefined);
  } finally {
    loadingDeliveries.value = false;
  }
}

function outcome(delivery: WebhookDelivery): string {
  if (delivery.status === "delivered") return `Answered ${delivery.response_status}`;
  const last = delivery.error ?? "not tried yet";
  if (delivery.status === "failed") return `${last}, after ${delivery.attempts} attempts`;
  return delivery.attempts && delivery.next_attempt_at
    ? `${last}; trying again ${formatRelative(delivery.next_attempt_at)}`
    : "Waiting to be sent";
}

watch(name, () => {
  created.value = null;
  open.value = null;
  void load();
});
onMounted(load);
</script>

<template>
  <section class="webhooks">
    <div>
      <h2>Webhooks</h2>
      <p class="muted small">
        Send this project's events to automation tools such as n8n, Make or Zapier. Each event is a signed JSON
        <code>POST</code>, retried for about a day until the receiver answers 2xx.
      </p>
    </div>

    <form class="create card" @submit.prevent="create">
      <div class="fields">
        <label class="field grow">
          <span>URL</span>
          <input v-model="url" class="input" type="url" required maxlength="2000" placeholder="https://example.com/hooks/mini-rag" />
        </label>
        <label class="field">
          <span>Description <span class="subtle">(optional)</span></span>
          <input v-model="description" class="input" maxlength="200" placeholder="n8n workflow" />
        </label>
      </div>
      <fieldset class="events">
        <legend>Events</legend>
        <label v-for="event in WEBHOOK_EVENTS" :key="event" class="event">
          <input v-model="events" type="checkbox" :value="event" />
          <span>
            <code>{{ event }}</code>
            <span class="subtle small">{{ EVENT_HELP[event] }}</span>
          </span>
        </label>
      </fieldset>
      <div class="actions">
        <button class="btn btn-primary" type="submit" :disabled="creating || !url.trim() || !events.length">
          <LoaderCircle v-if="creating" :size="16" class="spin" />
          <Plus v-else :size="16" />
          Add webhook
        </button>
      </div>
    </form>

    <div v-if="created" class="alert alert-success secret" role="status">
      <div>
        <p><strong>Webhook added.</strong> Keep its secret: it signs every delivery and is shown only now.</p>
        <code class="secret-value">{{ created.secret }}</code>
      </div>
      <div class="secret-actions">
        <button class="btn btn-sm" @click="copySecret">
          <Check v-if="copied" :size="14" />
          <Copy v-else :size="14" />
          {{ copied ? "Copied" : "Copy" }}
        </button>
        <button class="btn btn-ghost btn-sm" @click="created = null">Done</button>
      </div>
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-else-if="loading" class="skeleton list-skeleton" />
    <div v-else-if="!webhooks.length" class="empty card">
      <WebhookIcon :size="22" class="subtle" />
      <p class="muted">No webhooks yet. Add one above to hear when files are indexed.</p>
    </div>

    <ul v-else class="list">
      <li v-for="webhook in webhooks" :key="webhook.id" class="webhook card">
        <div class="row">
          <button class="btn btn-ghost btn-icon btn-sm" :aria-expanded="open === webhook.id" :aria-label="`Deliveries to ${webhook.url}`" @click="toggle(webhook)">
            <ChevronDown v-if="open === webhook.id" :size="16" />
            <ChevronRight v-else :size="16" />
          </button>
          <div class="info">
            <p class="url mono" :title="webhook.url">{{ webhook.url }}</p>
            <p class="subtle small">
              <template v-if="webhook.description">{{ webhook.description }} · </template>
              added {{ formatRelative(webhook.created_at) }}
            </p>
            <div class="badges">
              <span v-for="event in webhook.events" :key="event" class="badge mono">{{ event }}</span>
            </div>
          </div>
          <div v-if="confirmingDelete === webhook.id" class="confirm">
            <span class="small">Delete with its deliveries?</span>
            <button class="btn btn-danger btn-sm" :disabled="busy !== null" @click="remove(webhook)">Delete</button>
            <button class="btn btn-ghost btn-sm" @click="confirmingDelete = null">Cancel</button>
          </div>
          <div v-else class="buttons">
            <button class="btn btn-sm" :disabled="busy !== null" @click="ping(webhook)">
              <Send :size="14" />
              Send ping
            </button>
            <button class="btn btn-ghost btn-icon btn-sm" :aria-label="`Delete ${webhook.url}`" :title="`Delete ${webhook.url}`" @click="confirmingDelete = webhook.id">
              <Trash2 :size="15" />
            </button>
          </div>
        </div>

        <div v-if="open === webhook.id" class="deliveries">
          <div class="deliveries-head">
            <h4>Deliveries</h4>
            <button class="btn btn-ghost btn-sm" :disabled="loadingDeliveries" @click="loadDeliveries(deliveries?.offset ?? 0)">
              <RefreshCw :size="14" :class="{ spin: loadingDeliveries }" />
              Refresh
            </button>
          </div>
          <p v-if="deliveries && !deliveries.items.length" class="subtle small">Nothing sent yet.</p>
          <table v-else-if="deliveries" class="table">
            <thead>
              <tr>
                <th>Event</th>
                <th>Status</th>
                <th>Outcome</th>
                <th class="hide-sm">When</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="delivery in deliveries.items" :key="delivery.id">
                <td class="mono small">{{ delivery.event }}</td>
                <td>
                  <span
                    class="badge"
                    :class="{
                      'badge-success': delivery.status === 'delivered',
                      'badge-danger': delivery.status === 'failed',
                      'badge-warning': delivery.status === 'pending',
                    }"
                  >{{ delivery.status }}</span>
                </td>
                <td class="small muted">{{ outcome(delivery) }}</td>
                <td class="small subtle hide-sm">{{ formatRelative(delivery.created_at) }}</td>
              </tr>
            </tbody>
          </table>
          <PagerControls
            v-if="deliveries"
            :total="deliveries.total"
            :offset="deliveries.offset"
            :limit="deliveries.limit"
            noun="deliveries"
            @change="loadDeliveries"
          />
        </div>
      </li>
    </ul>

    <details class="verify card">
      <summary>Checking a delivery's signature</summary>
      <p class="small muted">
        Each delivery has <code>X-Mini-RAG-Signature: t=&lt;unix time&gt;,v1=&lt;hex&gt;</code>, an HMAC-SHA256 of
        <code>&lt;t&gt;.&lt;raw body&gt;</code> with the webhook's secret. Compute it from the raw body, compare in constant
        time, and reject old timestamps. <code>X-Mini-RAG-Delivery</code> stays the same on retries, to skip a delivery
        already handled.
      </p>
      <pre class="code"><code>import hmac, hashlib, time

def verify(secret: str, header: str, body: bytes, tolerance=300) -&gt; bool:
    parts = dict(item.split("=", 1) for item in header.split(","))
    signed = parts["t"].encode() + b"." + body
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    fresh = abs(time.time() - int(parts["t"])) &lt;= tolerance
    return fresh and hmac.compare_digest(expected, parts["v1"])</code></pre>
    </details>
  </section>
</template>

<style scoped>
.webhooks {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.create {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px;
}

.fields {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: 550;
}

.field.grow {
  flex: 1 1 340px;
}

.field .input {
  width: 100%;
  min-width: 220px;
}

.events {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 8px 16px;
  margin: 0;
  padding: 0;
  border: 0;
}

.events legend {
  margin-bottom: 6px;
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: 550;
}

.event {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  cursor: pointer;
}

.event input {
  width: 16px;
  height: 16px;
  margin-top: 2px;
  accent-color: var(--accent);
}

.event > span {
  display: flex;
  flex-direction: column;
}

.actions {
  display: flex;
  justify-content: flex-end;
}

.secret {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.secret-value {
  display: inline-block;
  margin-top: 6px;
  font-size: 13px;
  word-break: break-all;
  user-select: all;
}

.secret-actions {
  display: flex;
  gap: 6px;
}

.list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.webhook {
  padding: 12px 14px;
}

.row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.info {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.url {
  overflow: hidden;
  font-size: 13.5px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.badges {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 2px;
}

.buttons,
.confirm {
  display: flex;
  flex: none;
  align-items: center;
  gap: 6px;
}

.deliveries {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}

.deliveries-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.table {
  width: 100%;
  border-collapse: collapse;
}

.table th,
.table td {
  padding: 8px 10px;
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

@media (max-width: 640px) {
  .hide-sm {
    display: none;
  }
}

.empty {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 18px;
}

.list-skeleton {
  height: 90px;
  border-radius: var(--radius);
}

.verify {
  padding: 12px 16px;
}

.verify summary {
  font-weight: 600;
  cursor: pointer;
}

.verify p {
  margin: 10px 0;
}

.code {
  overflow-x: auto;
  margin: 0;
  padding: 12px;
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  font-size: 12.5px;
}

@media (max-width: 640px) {
  .row {
    flex-wrap: wrap;
  }
}
</style>
