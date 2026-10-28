<script setup lang="ts">
import { LoaderCircle, MailCheck } from "@lucide/vue";
import { ref } from "vue";

import { ApiError, api } from "@/api/client";
import AuthCard from "@/components/AuthCard.vue";

const email = ref("");
const busy = ref(false);
const sent = ref(false);
const error = ref<string | null>(null);

async function send() {
  if (busy.value) return;
  busy.value = true;
  error.value = null;
  try {
    await api.requestPasswordReset(email.value.trim());
    sent.value = true;
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "The link could not be sent.";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <AuthCard title="Reset your password" subtitle="We email you a link to choose a new one.">
    <div v-if="sent" class="alert alert-success" role="status">
      <MailCheck :size="18" />
      <span>
        If an account has <strong>{{ email }}</strong>, a link is on its way. It works once, for an hour. No email?
        Check the spam folder, or ask the server's administrator for a link.
      </span>
    </div>
    <form v-else @submit.prevent="send">
      <label class="field">
        <span>Email</span>
        <input v-model="email" class="input" type="email" autocomplete="email" required maxlength="254" />
      </label>
      <p v-if="error" class="error small" role="alert">{{ error }}</p>
      <button type="submit" class="btn btn-primary" :disabled="busy">
        <LoaderCircle v-if="busy" :size="16" class="spin" /> Email me a link
      </button>
    </form>
    <template #footer>
      <RouterLink to="/signin">Back to sign in</RouterLink>
    </template>
  </AuthCard>
</template>
