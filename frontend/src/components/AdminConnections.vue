<script setup lang="ts">
import { HardDrive, LoaderCircle, NotebookText, Plug, TriangleAlert } from "@lucide/vue";
import { onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { ApiError, api } from "@/api/client";
import type { Connection, ConnectionKind, ConnectionList } from "@/api/types";
import { useToasts } from "@/composables/useToasts";
import { formatRelative } from "@/lib/format";
import { goTo } from "@/lib/navigate";
import { signalMessage } from "@/lib/signals";

// The workspace's sign-ins to Notion and Google Drive, which Notion and Drive sources read
// through. Connecting leaves for the service's sign-in page, which sends the admin back here
// with ?connected=<id> or ?connection_error=<signal>.
const emit = defineEmits<{ changed: [] }>();

const KINDS: Record<ConnectionKind, { label: string; icon: typeof Plug; reads: string }> = {
  notion: { label: "Notion", icon: NotebookText, reads: "the pages you pick when signing in" },
  google_drive: { label: "Google Drive", icon: HardDrive, reads: "the account's Drive files, read only" },
};
const SETTINGS: Record<ConnectionKind, string> = {
  notion: "NOTION_CLIENT_ID and NOTION_CLIENT_SECRET",
  google_drive: "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET",
};

const route = useRoute();
const router = useRouter();
const toasts = useToasts();
const list = ref<ConnectionList | null>(null);
const error = ref<string | null>(null);
const starting = ref<ConnectionKind | null>(null);

const message = (caught: unknown) => (caught instanceof ApiError ? caught.message : undefined);

async function load() {
  try {
    list.value = await api.connections();
    error.value = null;
  } catch (caught) {
    error.value = message(caught) ?? "The connections could not be loaded.";
  }
}

/** Says how the sign-in went, once, and takes it out of the address. */
async function welcomeBack() {
  const { connected, connection_error: failed, ...rest } = route.query;
  if (typeof connected === "string") {
    const connection = list.value?.items.find((c) => c.id === connected);
    toasts.success("Connected", connection ? `${KINDS[connection.kind].label}: ${connection.account}.` : undefined);
    emit("changed");
  } else if (typeof failed === "string") {
    toasts.error("Nothing was connected", signalMessage(failed));
  } else {
    return;
  }
  await router.replace({ query: rest });
}

onMounted(async () => {
  await load();
  await welcomeBack();
});

async function connect(kind: ConnectionKind) {
  starting.value = kind;
  try {
    const { authorize_url } = await api.startConnection(kind, window.location.href.split("?")[0]!);
    goTo(authorize_url);
  } catch (caught) {
    toasts.error(`${KINDS[kind].label} could not be connected`, message(caught));
    starting.value = null;
  }
}

async function remove(connection: Connection) {
  const name = `${KINDS[connection.kind].label} (${connection.account})`;
  if (!window.confirm(`Remove ${name}? Its tokens are forgotten here; revoke its access at the service too.`)) return;
  try {
    await api.deleteConnection(connection.id);
    toasts.success("Connection removed", `${name} is no longer connected.`);
    emit("changed");
    await load();
  } catch (caught) {
    toasts.error("The connection could not be removed", message(caught));
  }
}
</script>

<template>
  <section class="connections" aria-labelledby="connections-title">
    <div>
      <h3 id="connections-title">Connections</h3>
      <p class="muted small">
        Sign the workspace in to Notion or Google Drive, so projects can keep their pages and files as sources. Only reading
        is allowed; connecting the same account again renews its connection.
      </p>
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-else-if="!list" class="skeleton list-skeleton" />
    <template v-else>
      <div class="services">
        <div v-for="(info, kind) in KINDS" :key="kind" class="service card">
          <component :is="info.icon" :size="18" class="subtle" aria-hidden="true" />
          <div class="service-text">
            <strong>{{ info.label }}</strong>
            <p class="subtle small">
              <template v-if="list.available.includes(kind)">Reads {{ info.reads }}.</template>
              <template v-else>Not set up on this server: its operator sets {{ SETTINGS[kind] }}.</template>
            </p>
          </div>
          <button
            type="button"
            class="btn btn-sm"
            :disabled="!list.available.includes(kind) || starting !== null"
            @click="connect(kind)"
          >
            <LoaderCircle v-if="starting === kind" :size="14" class="spin" />
            <Plug v-else :size="14" />
            Connect {{ info.label }}
          </button>
        </div>
      </div>
      <p v-if="list.available.length" class="subtle small">
        The redirect URI registered with each app is <code class="mono">{{ list.redirect_uri }}</code>.
      </p>

      <p v-if="!list.items.length" class="subtle small">No connections yet.</p>
      <ul v-else class="list">
        <li v-for="connection in list.items" :key="connection.id" class="item card" :aria-label="connection.account">
          <component :is="KINDS[connection.kind].icon" :size="16" class="subtle" aria-hidden="true" />
          <div class="info">
            <p>
              <strong>{{ connection.account }}</strong>
              <span class="badge">{{ KINDS[connection.kind].label }}</span>
            </p>
            <p class="subtle small">
              Connected {{ formatRelative(connection.created_at) }}{{ connection.created_by ? ` by ${connection.created_by}` : "" }} ·
              {{ connection.sources_count === 1 ? "1 source" : `${connection.sources_count} sources` }}
            </p>
            <p v-if="connection.last_error" class="small error">
              <TriangleAlert :size="13" aria-hidden="true" />
              {{ connection.last_error }}. Connect {{ KINDS[connection.kind].label }} again with this account.
            </p>
          </div>
          <button
            type="button"
            class="btn btn-ghost btn-sm"
            :aria-label="`Remove ${connection.account}`"
            :disabled="connection.sources_count > 0"
            :title="connection.sources_count > 0 ? 'Remove its sources first' : undefined"
            @click="remove(connection)"
          >
            Remove
          </button>
        </li>
      </ul>
    </template>
  </section>
</template>

<style scoped>
.connections {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.services {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 10px;
}

.service {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding: 12px 14px;
}

.service-text {
  flex: 1 1 140px;
  min-width: 0;
}

.service-text p,
.info p {
  margin: 2px 0 0;
}

.list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.item {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding: 10px 14px;
}

.info {
  flex: 1 1 220px;
  min-width: 0;
  overflow-wrap: anywhere;
}

.info p:first-child {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.error {
  display: flex;
  align-items: center;
  gap: 5px;
  color: var(--danger);
}

code {
  overflow-wrap: anywhere;
}

.list-skeleton {
  height: 96px;
  border-radius: var(--radius);
}
</style>
