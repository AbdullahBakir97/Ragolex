<script setup lang="ts">
import { CircleCheck, LoaderCircle } from "@lucide/vue";
import { ref } from "vue";

import { ApiError, api } from "@/api/client";
import AuthCard from "@/components/AuthCard.vue";
import { forgetLinkToken, takeLinkToken } from "@/lib/linkToken";

const STORAGE_KEY = "ragolex.password-reset";
const token = takeLinkToken(STORAGE_KEY);

const password = ref("");
const repeat = ref("");
const busy = ref(false);
const done = ref(false);
const error = ref<string | null>(token ? null : "This page needs the link from the email.");

async function reset() {
  if (busy.value || !token) return;
  if (password.value !== repeat.value) {
    error.value = "The two passwords differ.";
    return;
  }
  busy.value = true;
  error.value = null;
  try {
    await api.resetPassword(token, password.value);
    forgetLinkToken(STORAGE_KEY);
    done.value = true;
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "The password could not be changed.";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <AuthCard title="Choose a new password" subtitle="Every place you were signed in is signed out.">
    <div v-if="done" class="alert alert-success" role="status">
      <CircleCheck :size="18" />
      <span>Your password is changed. <RouterLink to="/signin">Sign in</RouterLink> with it.</span>
    </div>
    <form v-else @submit.prevent="reset">
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
            aria-describedby="new-password-help"
            :disabled="!token"
          />
        </label>
        <span id="new-password-help" class="subtle small">At least 10 characters.</span>
      </div>
      <label class="field">
        <span>The same again</span>
        <input v-model="repeat" class="input" type="password" autocomplete="new-password" required maxlength="128" :disabled="!token" />
      </label>
      <p v-if="error" class="error small" role="alert">{{ error }}</p>
      <button type="submit" class="btn btn-primary" :disabled="busy || !token">
        <LoaderCircle v-if="busy" :size="16" class="spin" /> Change password
      </button>
    </form>
    <template #footer>
      <RouterLink to="/forgot-password">Ask for a new link</RouterLink>
      <RouterLink to="/signin">Back to sign in</RouterLink>
    </template>
  </AuthCard>
</template>
