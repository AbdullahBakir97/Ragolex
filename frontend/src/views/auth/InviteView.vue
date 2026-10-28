<script setup lang="ts">
import { LoaderCircle, Users } from "@lucide/vue";
import { computed, onMounted, ref } from "vue";

import { ApiError, api } from "@/api/client";
import type { InvitationPreview } from "@/api/types";
import AuthCard from "@/components/AuthCard.vue";
import { useSession } from "@/composables/useSession";
import { formatDate } from "@/lib/format";
import { forgetLinkToken, takeLinkToken } from "@/lib/linkToken";
import { reloadAt } from "@/lib/navigate";

// An invitation link: who invited whom to which workspace, and joining it, as
// the account that is signed in, by signing in first, or with a new account.
const STORAGE_KEY = "ragolex.invitation";
const token = takeLinkToken(STORAGE_KEY);
const { session, load, signOut } = useSession();

const preview = ref<InvitationPreview | null>(null);
const loading = ref(true);
const error = ref<string | null>(token ? null : "This page needs the link from the invitation.");
const name = ref("");
const password = ref("");
const busy = ref(false);

const article = (role: string) => (role === "owner" || role === "admin" || role === "editor" ? "an" : "a");
const signedInAsInvited = computed(() => !!session.value && session.value.user.email === preview.value?.email);

onMounted(async () => {
  if (!token) {
    loading.value = false;
    return;
  }
  try {
    [preview.value] = await Promise.all([api.invitation(token), load()]);
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "The invitation could not be loaded.";
  } finally {
    loading.value = false;
  }
});

async function accept() {
  if (!token || busy.value) return;
  busy.value = true;
  error.value = null;
  try {
    await api.acceptInvitation(token, signedInAsInvited.value ? {} : { name: name.value.trim(), password: password.value });
    forgetLinkToken(STORAGE_KEY);
    reloadAt("/");
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "The invitation could not be accepted.";
    busy.value = false;
  }
}
</script>

<template>
  <AuthCard
    title="Join a workspace"
    :subtitle="preview ? `${preview.invited_by ?? 'An administrator'} invited you to ${preview.workspace}.` : undefined"
  >
    <div v-if="loading" class="skeleton loading" />
    <template v-else-if="preview">
      <div class="offer card">
        <Users :size="18" />
        <p>
          Join <strong>{{ preview.workspace }}</strong> as {{ article(preview.role) }} <strong>{{ preview.role }}</strong>,
          with <strong>{{ preview.email }}</strong>.
          <span class="subtle small">The link works until {{ formatDate(preview.expires_at) }}.</span>
        </p>
      </div>

      <template v-if="signedInAsInvited">
        <p v-if="error" class="error small" role="alert">{{ error }}</p>
        <button type="button" class="btn btn-primary" :disabled="busy" @click="accept">
          <LoaderCircle v-if="busy" :size="16" class="spin" /> Join {{ preview.workspace }}
        </button>
      </template>

      <template v-else-if="session">
        <p class="muted">
          You are signed in as <strong>{{ session.user.email }}</strong>, but this invitation is for
          <strong>{{ preview.email }}</strong>. Sign out, then open the link again.
        </p>
        <button type="button" class="btn" @click="signOut">Sign out</button>
      </template>

      <template v-else-if="preview.has_account">
        <p class="muted">{{ preview.email }} has an account: sign in with it, and you come back here to join.</p>
        <RouterLink class="btn btn-primary" :to="{ path: '/signin', query: { next: '/invite' } }">Sign in to join</RouterLink>
      </template>

      <form v-else @submit.prevent="accept">
        <p class="muted small">Create your account to join.</p>
        <label class="field">
          <span>Your name</span>
          <input v-model="name" class="input" autocomplete="name" required maxlength="100" />
        </label>
        <div class="field">
          <label class="field">
            <span>Password</span>
            <input
              v-model="password"
              class="input"
              type="password"
              autocomplete="new-password"
              required
              minlength="10"
              maxlength="128"
              aria-describedby="invite-password-help"
            />
          </label>
          <span id="invite-password-help" class="subtle small">At least 10 characters.</span>
        </div>
        <p v-if="error" class="error small" role="alert">{{ error }}</p>
        <button type="submit" class="btn btn-primary" :disabled="busy">
          <LoaderCircle v-if="busy" :size="16" class="spin" /> Create account and join
        </button>
      </form>
    </template>
    <p v-else class="error" role="alert">{{ error }}</p>
  </AuthCard>
</template>

<style scoped>
.loading {
  height: 120px;
  border-radius: var(--radius);
}

.offer {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 12px 14px;
  background: var(--surface-2);
  box-shadow: none;
}

.offer svg {
  flex: none;
  margin-top: 2px;
  color: var(--accent);
}

.offer .small {
  display: block;
  margin-top: 4px;
}
</style>
