<script setup lang="ts">
import { Check, Copy, LoaderCircle, MessagesSquare, Plus, Trash2 } from "@lucide/vue";
import { computed, onMounted, reactive, ref, watch } from "vue";

import { ApiError, api } from "@/api/client";
import type { BotKind, ChatBot } from "@/api/types";
import TagInput from "@/components/TagInput.vue";
import { useProject } from "@/composables/useProject";
import { useToasts } from "@/composables/useToasts";
import { formatRelative } from "@/lib/format";

// The project's assistants in Telegram, Slack and WhatsApp: added with the chat
// app's credentials, then answering there from the project's documents.
const { name, tags: projectTags } = useProject();
const toasts = useToasts();
const tagSuggestions = computed(() => projectTags.value.map((t) => t.tag));

interface Field {
  key: string;
  label: string;
  secret: boolean;
  placeholder: string;
}

const KINDS: { kind: BotKind; label: string; fields: Field[]; steps: string[] }[] = [
  {
    kind: "telegram",
    label: "Telegram",
    fields: [{ key: "token", label: "Bot token", secret: true, placeholder: "123456789:AA…" }],
    steps: [
      "In Telegram, message @BotFather, send /newbot and follow its questions.",
      "Paste the token it gives you here. The bot connects itself to this server.",
    ],
  },
  {
    kind: "slack",
    label: "Slack",
    fields: [
      { key: "bot_token", label: "Bot token", secret: true, placeholder: "xoxb-…" },
      { key: "signing_secret", label: "Signing secret", secret: true, placeholder: "From Basic Information" },
    ],
    steps: [
      "Create an app at api.slack.com/apps. Under OAuth & Permissions, add the bot scopes app_mentions:read, chat:write and im:history, and install it.",
      "Paste the Bot User OAuth Token and, from Basic Information, the Signing Secret here.",
      "After adding the bot, paste its webhook URL as the Request URL under Event Subscriptions, and subscribe to app_mention and message.im.",
    ],
  },
  {
    kind: "whatsapp",
    label: "WhatsApp",
    fields: [
      { key: "access_token", label: "Access token", secret: true, placeholder: "EAAG…" },
      { key: "phone_number_id", label: "Phone number ID", secret: false, placeholder: "1055…" },
      { key: "app_secret", label: "App secret", secret: true, placeholder: "From App settings › Basic" },
    ],
    steps: [
      "In a Meta app with the WhatsApp product, copy the phone number ID and an access token from API Setup, and the app secret from App settings › Basic.",
      "After adding the bot, set its webhook URL as the Callback URL and its verify token under WhatsApp › Configuration, and subscribe to messages.",
    ],
  },
];
const KIND_LABEL: Record<BotKind, string> = { telegram: "Telegram", slack: "Slack", whatsapp: "WhatsApp" };

const bots = ref<ChatBot[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);

async function load() {
  loading.value = true;
  try {
    bots.value = (await api.bots(name.value)).items;
    error.value = null;
  } catch (caught) {
    const empty = caught instanceof ApiError && caught.signal === "project_not_found";
    bots.value = [];
    error.value = empty ? null : caught instanceof ApiError ? caught.message : "Bots could not be loaded.";
  } finally {
    loading.value = false;
  }
}

// Adding one.
const kind = ref<BotKind>("telegram");
const form = reactive({ name: "", tags: [] as string[], credentials: {} as Record<string, string> });
const creating = ref(false);
const created = ref<ChatBot | null>(null);
const chosen = computed(() => KINDS.find((k) => k.kind === kind.value)!);
const complete = computed(() => form.name.trim() && chosen.value.fields.every((f) => form.credentials[f.key]?.trim()));

watch(kind, () => (form.credentials = {}));

async function create() {
  if (!complete.value || creating.value) return;
  creating.value = true;
  try {
    const credentials = Object.fromEntries(chosen.value.fields.map((f) => [f.key, form.credentials[f.key]!.trim()]));
    created.value = await api.createBot(name.value, { kind: kind.value, name: form.name.trim(), credentials, tags: form.tags });
    form.name = "";
    form.tags = [];
    form.credentials = {};
    await load();
  } catch (caught) {
    toasts.error("The bot could not be added", caught instanceof ApiError ? caught.message : undefined);
  } finally {
    creating.value = false;
  }
}

// Each bot's actions.
const copied = ref<string | null>(null);
const confirmingDelete = ref<string | null>(null);
const busy = ref<string | null>(null);

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    copied.value = text;
  } catch {
    toasts.error("Copying failed", "Select the text and copy it by hand.");
  }
}

async function setEnabled(bot: ChatBot, enabled: boolean) {
  busy.value = bot.id;
  try {
    await api.updateBot(name.value, bot.id, { enabled });
    toasts.success(enabled ? "Bot turned on" : "Bot turned off", enabled ? `${bot.name} answers again.` : `${bot.name} ignores messages now.`);
    await load();
  } catch (caught) {
    toasts.error("The bot could not be changed", caught instanceof ApiError ? caught.message : undefined);
  } finally {
    busy.value = null;
  }
}

async function remove(bot: ChatBot) {
  busy.value = bot.id;
  try {
    await api.deleteBot(name.value, bot.id);
    toasts.success("Bot removed", `${bot.name} no longer answers; its conversations stay.`);
    if (created.value?.id === bot.id) created.value = null;
    await load();
  } catch (caught) {
    toasts.error("The bot could not be removed", caught instanceof ApiError ? caught.message : undefined);
  } finally {
    busy.value = null;
    confirmingDelete.value = null;
  }
}

watch(name, () => {
  created.value = null;
  void load();
});
onMounted(load);
</script>

<template>
  <section class="bots">
    <div>
      <h2>Chat bots</h2>
      <p class="muted small">
        Let people ask this project in Telegram, Slack or WhatsApp. The bot answers from the documents with its sources,
        keeps each chat's conversation for follow-up questions, and counts against the workspace's limits.
      </p>
    </div>

    <form class="create card" @submit.prevent="create">
      <fieldset class="kinds">
        <legend>Chat app</legend>
        <label v-for="option in KINDS" :key="option.kind" class="kind" :class="{ chosen: kind === option.kind }">
          <input v-model="kind" type="radio" name="kind" :value="option.kind" />
          {{ option.label }}
        </label>
      </fieldset>
      <ol class="steps small muted">
        <li v-for="step in chosen.steps" :key="step">{{ step }}</li>
      </ol>
      <div class="fields">
        <label class="field">
          <span>Name</span>
          <input v-model="form.name" class="input" maxlength="100" placeholder="Help desk" required />
        </label>
        <label v-for="field in chosen.fields" :key="`${kind}-${field.key}`" class="field">
          <span>{{ field.label }}</span>
          <input
            v-model="form.credentials[field.key]"
            class="input mono"
            :type="field.secret ? 'password' : 'text'"
            :placeholder="field.placeholder"
            autocomplete="off"
            spellcheck="false"
            maxlength="4096"
            required
          />
        </label>
      </div>
      <div class="field">
        <span>Answer only from documents tagged</span>
        <TagInput v-model="form.tags" :suggestions="tagSuggestions" label="Answer only from documents tagged" placeholder="Any document" />
      </div>
      <div class="actions">
        <button class="btn btn-primary" type="submit" :disabled="creating || !complete">
          <LoaderCircle v-if="creating" :size="16" class="spin" />
          <Plus v-else :size="16" />
          Add bot
        </button>
      </div>
    </form>

    <div v-if="created" class="alert alert-success" role="status">
      <div class="created">
        <p v-if="created.kind === 'telegram'">
          <strong>{{ created.name }} is ready.</strong> Message <strong>{{ created.account }}</strong> in Telegram to try it.
        </p>
        <p v-else>
          <strong>{{ created.name }} is added as {{ created.account }}.</strong>
          One step left: paste its webhook URL{{ created.kind === "whatsapp" ? " and verify token" : "" }} into the
          {{ KIND_LABEL[created.kind] }} app's settings, as shown in its card below.
        </p>
      </div>
      <button class="btn btn-ghost btn-sm" @click="created = null">Done</button>
    </div>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-else-if="loading" class="skeleton list-skeleton" />
    <div v-else-if="!bots.length" class="empty card">
      <MessagesSquare :size="22" class="subtle" />
      <p class="muted">No bots yet. Add one above to answer in a chat app.</p>
    </div>

    <ul v-else class="list">
      <li v-for="bot in bots" :key="bot.id" class="bot card" :aria-label="bot.name">
        <div class="row">
          <div class="info">
            <p class="title">
              <strong>{{ bot.name }}</strong>
              <span class="badge">{{ KIND_LABEL[bot.kind] }}</span>
              <span v-if="!bot.enabled" class="badge badge-warning">Off</span>
            </p>
            <p class="subtle small">
              {{ bot.account }} · added {{ formatRelative(bot.created_at) }} ·
              {{ bot.last_message_at ? `last message ${formatRelative(bot.last_message_at)}` : "no messages yet" }}
            </p>
            <div v-if="bot.tags.length" class="badges">
              <span v-for="tag in bot.tags" :key="tag" class="chip">{{ tag }}</span>
            </div>
          </div>
          <div v-if="confirmingDelete === bot.id" class="confirm">
            <span class="small">Remove this bot?</span>
            <button class="btn btn-danger btn-sm" :disabled="busy !== null" @click="remove(bot)">Remove</button>
            <button class="btn btn-ghost btn-sm" @click="confirmingDelete = null">Cancel</button>
          </div>
          <div v-else class="buttons">
            <label class="switch small">
              <input type="checkbox" :checked="bot.enabled" :disabled="busy !== null" @change="setEnabled(bot, ($event.target as HTMLInputElement).checked)" />
              Answers
            </label>
            <button class="btn btn-ghost btn-icon btn-sm" :aria-label="`Remove ${bot.name}`" :title="`Remove ${bot.name}`" @click="confirmingDelete = bot.id">
              <Trash2 :size="15" />
            </button>
          </div>
        </div>
        <p v-if="bot.last_error" class="alert alert-warning small" role="status">
          Last problem{{ bot.last_error_at ? ` (${formatRelative(bot.last_error_at)})` : "" }}: {{ bot.last_error }}
        </p>
        <dl v-if="bot.kind !== 'telegram'" class="setup small">
          <dt>Webhook URL</dt>
          <dd>
            <code class="mono">{{ bot.webhook_url }}</code>
            <button class="btn btn-ghost btn-icon btn-sm" :aria-label="`Copy the webhook URL of ${bot.name}`" @click="copy(bot.webhook_url)">
              <component :is="copied === bot.webhook_url ? Check : Copy" :size="14" />
            </button>
          </dd>
          <template v-if="bot.verify_token">
            <dt>Verify token</dt>
            <dd>
              <code class="mono">{{ bot.verify_token }}</code>
              <button class="btn btn-ghost btn-icon btn-sm" :aria-label="`Copy the verify token of ${bot.name}`" @click="copy(bot.verify_token)">
                <component :is="copied === bot.verify_token ? Check : Copy" :size="14" />
              </button>
            </dd>
          </template>
        </dl>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.bots {
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

.kinds {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0;
  padding: 0;
  border: 0;
}

.kinds legend {
  margin-bottom: 6px;
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: 550;
}

.kind {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  cursor: pointer;
}

.kind.chosen {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.steps {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 0;
  padding-left: 18px;
}

.fields {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}

.actions {
  display: flex;
  justify-content: flex-end;
}

.created p {
  margin: 0;
}

.alert-success {
  justify-content: space-between;
}

.list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.bot {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px;
}

.row {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px 12px;
}

.info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.badges {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.buttons,
.confirm {
  display: flex;
  align-items: center;
  gap: 8px;
}

.switch {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-2);
}

.setup {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 4px 12px;
  align-items: center;
  margin: 0;
}

.setup dt {
  color: var(--text-2);
  font-weight: 550;
}

.setup dd {
  display: flex;
  align-items: center;
  gap: 4px;
  margin: 0;
  min-width: 0;
}

.setup code {
  overflow-wrap: anywhere;
}

.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 28px 16px;
  text-align: center;
}

.list-skeleton {
  height: 140px;
  border-radius: var(--radius);
}
</style>
