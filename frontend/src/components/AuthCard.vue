<script setup lang="ts">
import BrandMark from "@/components/BrandMark.vue";

// The frame of the pages people see before they are signed in.
defineProps<{ title: string; subtitle?: string }>();
</script>

<template>
  <div class="auth-page">
    <RouterLink to="/" class="brand-link" aria-label="Ragolex home"><BrandMark /></RouterLink>
    <section class="card auth-card" aria-labelledby="auth-title">
      <div class="heading">
        <h1 id="auth-title">{{ title }}</h1>
        <p v-if="subtitle" class="muted">{{ subtitle }}</p>
      </div>
      <slot />
    </section>
    <div v-if="$slots.footer" class="footer small"><slot name="footer" /></div>
  </div>
</template>

<style scoped>
.auth-page {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 20px;
  min-height: 100vh;
  padding: 48px 16px;
}

.brand-link {
  color: inherit;
  text-decoration: none;
}

.auth-card {
  display: flex;
  flex-direction: column;
  gap: 18px;
  width: min(420px, 100%);
  padding: 26px;
}

.heading {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.heading h1 {
  font-size: 20px;
}

.footer {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 4px 16px;
  color: var(--text-2);
}

/* The forms on these pages: one field a line. */
.auth-card :deep(form) {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* Links among words are underlined, not told apart by colour alone. */
.footer :deep(a),
.auth-card :deep(p a),
.auth-card :deep(.alert a) {
  text-decoration: underline;
}

.auth-card :deep(.error) {
  color: var(--danger);
}

.auth-card :deep(.btn-primary) {
  width: 100%;
}
</style>
