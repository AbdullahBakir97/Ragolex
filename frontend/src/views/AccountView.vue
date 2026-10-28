<script setup lang="ts">
import { KeyRound, LoaderCircle, LogOut } from "@lucide/vue";
import { onMounted, ref } from "vue";

import { apiKey } from "@/api/auth";
import { ApiError, api } from "@/api/client";
import PageHeader from "@/components/PageHeader.vue";
import { useSession } from "@/composables/useSession";
import { useToasts } from "@/composables/useToasts";
import { formatDate } from "@/lib/format";

// The signed-in user: their workspaces, their password, and signing out.
const { session, loaded, load, signOut, switchWorkspace } = useSession();
const toasts = useToasts();

const current = ref("");
const password = ref("");
const repeat = ref("");
const busy = ref(false);
const error = ref<string | null>(null);

onMounted(() => {
  if (!loaded.value) void load();
});

async function changePassword() {
  if (busy.value) return;
  if (password.value !== repeat.value) {
    error.value = "The two new passwords differ.";
    return;
  }
  busy.value = true;
  error.value = null;
  try {
    await api.changePassword(current.value, password.value);
    current.value = password.value = repeat.value = "";
    toasts.success("Password changed", "Every other place you were signed in is signed out.");
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "The password could not be changed.";
  } finally {
    busy.value = false;
  }
}

async function switchTo(name: string) {
  try {
    await switchWorkspace(name);
  } catch (caught) {
    toasts.error("The workspace could not be opened", caught instanceof ApiError ? caught.message : undefined);
  }
}
</script>

<template>
  <div class="page">
    <PageHeader title="Account" subtitle="Your workspaces, your password, and signing out." />

    <div v-if="!loaded" class="skeleton block" />

    <template v-else-if="session">
      <section class="card panel" aria-labelledby="profile-title">
        <h2 id="profile-title">{{ session.user.name }}</h2>
        <p class="muted">{{ session.user.email }}</p>
        <p class="subtle small">Signed in until {{ formatDate(session.expires_at) }}.</p>
        <button type="button" class="btn sign-out" @click="signOut"><LogOut :size="15" /> Sign out</button>
      </section>

      <section class="card panel" aria-labelledby="workspaces-title">
        <h2 id="workspaces-title">Workspaces</h2>
        <ul class="workspaces">
          <li v-for="workspace in session.workspaces" :key="workspace.name">
            <span class="workspace-name">{{ workspace.name }}</span>
            <span class="chip">{{ workspace.role }}</span>
            <span v-if="workspace.name === session.workspace.name" class="badge badge-accent">Open now</span>
            <button v-else type="button" class="btn btn-sm" @click="switchTo(workspace.name)">Open</button>
          </li>
        </ul>
      </section>

      <section class="card panel" aria-labelledby="password-title">
        <h2 id="password-title">Change password</h2>
        <form class="password" @submit.prevent="changePassword">
          <input type="email" autocomplete="username" :value="session.user.email" hidden />
          <label class="field">
            <span>Current password</span>
            <input v-model="current" class="input" type="password" autocomplete="current-password" required maxlength="128" />
          </label>
          <div class="field">
            <label class="field">
              <span>New password</span>
              <input
                v-model="password"
                class="input"
                type="password"
                autocomplete="new-password"
                required
                minlength="10"
                maxlength="128"
                aria-describedby="account-password-help"
              />
            </label>
            <span id="account-password-help" class="subtle small">At least 10 characters.</span>
          </div>
          <label class="field">
            <span>New password again</span>
            <input v-model="repeat" class="input" type="password" autocomplete="new-password" required maxlength="128" />
          </label>
          <p v-if="error" class="error small" role="alert">{{ error }}</p>
          <div>
            <button type="submit" class="btn btn-primary" :disabled="busy">
              <LoaderCircle v-if="busy" :size="16" class="spin" /> Change password
            </button>
          </div>
        </form>
      </section>
    </template>

    <div v-else class="alert">
      <KeyRound :size="18" class="subtle" />
      <span class="muted">
        {{ apiKey ? "This browser uses an API key, not an account." : "Nobody is signed in: authentication is off on this server." }}
        <button v-if="apiKey" type="button" class="btn btn-sm link" @click="signOut">Sign out</button>
      </span>
    </div>
  </div>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 20px;
  max-width: 720px;
  margin: 0 auto;
  padding: 28px 32px 48px;
}

@media (max-width: 640px) {
  .page {
    padding: 20px 16px 40px;
  }
}

.block {
  height: 220px;
  border-radius: var(--radius);
}

.panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 18px 20px;
}

.panel h2 {
  font-size: 16px;
}

.sign-out {
  align-self: flex-start;
  margin-top: 4px;
}

.workspaces {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
}

.workspaces li {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 8px 0;
  border-bottom: 1px solid var(--border);
}

.workspaces li:last-child {
  border-bottom: 0;
}

.workspace-name {
  flex: 1;
  min-width: 0;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.password {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-width: 360px;
}

.error {
  color: var(--danger);
}

.link {
  margin-left: 8px;
}
</style>
