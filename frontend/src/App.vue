<script setup lang="ts">
import { Menu } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { signInNeeded } from "@/api/auth";
import AppSidebar from "@/components/AppSidebar.vue";
import BrandMark from "@/components/BrandMark.vue";
import ToastHost from "@/components/ToastHost.vue";

const route = useRoute();
const router = useRouter();
const menuOpen = ref(false);
// Sign-in, sign-up and the links from emails show on their own, without the app around them.
const bare = computed(() => route.meta.public === true);
// Nothing shows until the first page is known: the app around a public page would
// load data, and its refusal would send that page to sign in.
const ready = ref(false);
void router.isReady().then(() => (ready.value = true));

// The server wants a key or a session: sign in, then come back here.
watch(signInNeeded, (needed) => {
  if (!needed) return;
  signInNeeded.value = false;
  if (!bare.value) void router.replace({ name: "signin", query: { next: route.fullPath } });
});

// On small screens the sidebar is a drawer: close it after navigating.
watch(
  () => route.fullPath,
  () => (menuOpen.value = false),
);
</script>

<template>
  <template v-if="!ready" />
  <div v-else-if="bare" class="bare">
    <main><RouterView /></main>
    <ToastHost />
  </div>
  <div v-else class="shell" :class="{ 'menu-open': menuOpen }">
    <header class="topbar">
      <button class="btn btn-ghost btn-icon" aria-label="Open navigation" @click="menuOpen = true">
        <Menu :size="20" />
      </button>
      <RouterLink to="/" class="topbar-brand"><BrandMark /></RouterLink>
    </header>

    <div class="scrim" aria-hidden="true" @click="menuOpen = false" />
    <AppSidebar class="sidebar" @close="menuOpen = false" />

    <main class="main">
      <RouterView />
    </main>
    <ToastHost />
  </div>
</template>

<style scoped>
.shell {
  display: grid;
  grid-template-columns: var(--sidebar) minmax(0, 1fr);
  min-height: 100vh;
}

.sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
}

.main {
  min-width: 0;
}

.topbar,
.scrim {
  display: none;
}

@media (max-width: 860px) {
  .shell {
    grid-template-columns: minmax(0, 1fr);
  }

  .topbar {
    position: sticky;
    top: 0;
    z-index: 20;
    display: flex;
    align-items: center;
    gap: 8px;
    height: 52px;
    padding: 0 8px;
    border-bottom: 1px solid var(--border);
    background: var(--surface);
  }

  .topbar-brand {
    color: inherit;
    text-decoration: none;
  }

  .sidebar {
    position: fixed;
    inset: 0 auto 0 0;
    z-index: 40;
    width: min(var(--sidebar), 86vw);
    transform: translateX(-100%);
    transition: transform 0.2s ease;
    box-shadow: var(--shadow-lg);
  }

  .menu-open .sidebar {
    transform: none;
  }

  .scrim {
    position: fixed;
    inset: 0;
    z-index: 30;
    background: rgb(0 0 0 / 35%);
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.2s;
  }

  .menu-open .scrim {
    display: block;
    opacity: 1;
    pointer-events: auto;
  }
}
</style>
