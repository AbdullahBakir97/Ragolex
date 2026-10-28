<script setup lang="ts">
import { KeyRound, LoaderCircle } from "@lucide/vue";
import { computed, ref } from "vue";
import { useRoute } from "vue-router";

import { safeNext, signInReason } from "@/api/auth";
import { ApiError, api } from "@/api/client";
import ApiKeyDialog from "@/components/ApiKeyDialog.vue";
import AuthCard from "@/components/AuthCard.vue";
import { reloadAt } from "@/lib/navigate";

const route = useRoute();
const next = computed(() => safeNext(route.query.next));

const email = ref("");
const password = ref("");
const busy = ref(false);
const error = ref<string | null>(null);
const keyDialog = ref<InstanceType<typeof ApiKeyDialog> | null>(null);
// Shown once: why the app came here, such as a session that ended.
const reason = signInReason.value;
signInReason.value = null;

async function signIn() {
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
  <AuthCard title="Sign in" subtitle="With the email and password of your Ragolex account.">
    <div v-if="reason" class="alert alert-warning small" role="status">{{ reason }}</div>
    <form @submit.prevent="signIn">
      <label class="field">
        <span>Email</span>
        <input v-model="email" class="input" type="email" autocomplete="username" required maxlength="254" />
      </label>
      <div class="password">
        <label class="field">
          <span>Password</span>
          <input v-model="password" class="input" type="password" autocomplete="current-password" required maxlength="128" />
        </label>
        <RouterLink to="/forgot-password" class="small forgot">Forgot your password?</RouterLink>
      </div>
      <p v-if="error" class="error small" role="alert">{{ error }}</p>
      <button type="submit" class="btn btn-primary" :disabled="busy">
        <LoaderCircle v-if="busy" :size="16" class="spin" /> Sign in
      </button>
    </form>
    <button type="button" class="btn btn-ghost key" @click="keyDialog?.open()">
      <KeyRound :size="16" /> Use an API key instead
    </button>
    <template #footer>
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
