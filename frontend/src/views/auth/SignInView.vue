<script setup lang="ts">
import { Building2, KeyRound, LoaderCircle } from "@lucide/vue";
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { safeNext, signInReason } from "@/api/auth";
import { ApiError, api } from "@/api/client";
import ApiKeyDialog from "@/components/ApiKeyDialog.vue";
import AuthCard from "@/components/AuthCard.vue";
import { useSite } from "@/composables/useSite";
import { reloadAt } from "@/lib/navigate";
import { signalMessage } from "@/lib/signals";

const route = useRoute();
const next = computed(() => safeNext(route.query.next));
// On a workspace's own domain, signing in opens that workspace, and nobody signs up.
const { site, load } = useSite();
onMounted(load);

const email = ref("");
const password = ref("");
const busy = ref(false);
const error = ref<string | null>(null);
const keyDialog = ref<InstanceType<typeof ApiKeyDialog> | null>(null);
// Shown once: why the app came here, such as a session that ended.
const reason = signInReason.value;
signInReason.value = null;
// Back from the organisation's sign-in, when it did not work.
const ssoError = typeof route.query.sso_error === "string" ? signalMessage(route.query.sso_error) : null;
// Single sign-on: the email finds the workspace whose identity provider signs it in.
const sso = ref(ssoError !== null);

function toggleSso() {
  sso.value = !sso.value;
  error.value = null;
}

async function signInWithSso() {
  if (busy.value) return;
  busy.value = true;
  error.value = null;
  try {
    const { start_url } = await api.ssoDiscover(email.value.trim());
    reloadAt(`${start_url}&next=${encodeURIComponent(next.value)}`);
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "Single sign-on could not start.";
    busy.value = false;
  }
}

async function signIn() {
  if (sso.value) return signInWithSso();
  if (busy.value) return;
  busy.value = true;
  error.value = null;
  try {
    await api.signIn(email.value.trim(), password.value);
    // Everything starts again, signed in, where the app was going.
    reloadAt(next.value);
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "Signing in failed.";
    busy.value = false;
  }
}
</script>

<template>
  <AuthCard
    :title="site?.workspace ? `Sign in to ${site.workspace}` : 'Sign in'"
    subtitle="With the email and password of your Ragolex account."
  >
    <div v-if="reason" class="alert alert-warning small" role="status">{{ reason }}</div>
    <div v-if="ssoError" class="alert alert-danger small" role="alert">{{ ssoError }}</div>
    <form @submit.prevent="signIn">
      <label class="field">
        <span>Email</span>
        <input v-model="email" class="input" type="email" autocomplete="username" required maxlength="254" />
      </label>
      <div v-if="!sso" class="password">
        <label class="field">
          <span>Password</span>
          <input v-model="password" class="input" type="password" autocomplete="current-password" required maxlength="128" />
        </label>
        <RouterLink to="/forgot-password" class="small forgot">Forgot your password?</RouterLink>
      </div>
      <p v-if="error" class="error small" role="alert">{{ error }}</p>
      <p v-if="sso" class="subtle small">You will sign in with your organisation's account.</p>
      <button type="submit" class="btn btn-primary" :disabled="busy">
        <LoaderCircle v-if="busy" :size="16" class="spin" /> {{ sso ? "Continue" : "Sign in" }}
      </button>
    </form>
    <button type="button" class="btn btn-ghost key" @click="toggleSso">
      <Building2 :size="16" /> {{ sso ? "Sign in with a password instead" : "Sign in with single sign-on" }}
    </button>
    <button type="button" class="btn btn-ghost key" @click="keyDialog?.open()">
      <KeyRound :size="16" /> Use an API key instead
    </button>
    <template v-if="!site || site.signup_enabled" #footer>
      <span>New here? <RouterLink :to="{ path: '/signup', query: route.query }">Create an account</RouterLink></span>
    </template>
    <ApiKeyDialog ref="keyDialog" :next="next" />
  </AuthCard>
</template>

<style scoped>
.password {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.forgot {
  align-self: flex-end;
}

.key {
  align-self: center;
}
</style>
