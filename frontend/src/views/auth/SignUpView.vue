<script setup lang="ts">
import { LoaderCircle } from "@lucide/vue";
import { ref, watch } from "vue";

import { ApiError, api } from "@/api/client";
import AuthCard from "@/components/AuthCard.vue";
import { reloadAt } from "@/lib/navigate";

const name = ref("");
const email = ref("");
const workspace = ref("");
const password = ref("");
const busy = ref(false);
const error = ref<string | null>(null);

// Until it is edited, the workspace's name follows the email's domain or name.
const workspaceEdited = ref(false);
watch(email, (value) => {
  if (workspaceEdited.value) return;
  const [user = "", domain = ""] = value.toLowerCase().split("@");
  const base = domain.split(".")[0] || user;
  workspace.value = base.replace(/[^a-z0-9_-]+/g, "-").replace(/^[-_]+|-+$/g, "").slice(0, 64);
});

async function signUp() {
  if (busy.value) return;
  busy.value = true;
  error.value = null;
  try {
    await api.signUp({ name: name.value.trim(), email: email.value.trim(), workspace: workspace.value, password: password.value });
    reloadAt("/");
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "The account could not be created.";
    busy.value = false;
  }
}
</script>

<template>
  <AuthCard title="Create an account" subtitle="You get a workspace of your own; invite your team to it later.">
    <form @submit.prevent="signUp">
      <label class="field">
        <span>Your name</span>
        <input v-model="name" class="input" autocomplete="name" required maxlength="100" />
      </label>
      <label class="field">
        <span>Email</span>
        <input v-model="email" class="input" type="email" autocomplete="email" required maxlength="254" />
      </label>
      <div class="field">
        <label class="field">
          <span>Workspace</span>
          <input
            v-model="workspace"
            class="input mono"
            required
            pattern="[a-z0-9][a-z0-9_\-]{1,63}"
            aria-describedby="workspace-help"
            @input="workspaceEdited = true"
          />
        </label>
        <span id="workspace-help" class="subtle small">2 to 64 lower-case letters, digits, - and _.</span>
      </div>
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
            aria-describedby="password-help"
          />
        </label>
        <span id="password-help" class="subtle small">At least 10 characters.</span>
      </div>
      <p v-if="error" class="error small" role="alert">{{ error }}</p>
      <button type="submit" class="btn btn-primary" :disabled="busy">
        <LoaderCircle v-if="busy" :size="16" class="spin" /> Create account
      </button>
    </form>
    <template #footer>
      <span>Have an account? <RouterLink to="/signin">Sign in</RouterLink></span>
    </template>
  </AuthCard>
</template>
