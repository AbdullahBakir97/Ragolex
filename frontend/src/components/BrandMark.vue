<template>
  <span class="brand">
    <svg class="logo" viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="8" fill="var(--accent)" />
      <path
        d="M9 10h9a5 5 0 0 1 0 10h-2l5 5"
        fill="none"
        stroke="var(--on-accent)"
        stroke-width="2.6"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
      <circle cx="10" cy="21" r="2" fill="var(--on-accent)" opacity="0.65" />
    </svg>
    <span class="name">Ragolex</span>
  </span>
</template>

<style scoped>
.brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.logo {
  width: 28px;
  height: 28px;
}

.name {
  font-size: 15px;
  font-weight: 650;
  letter-spacing: -0.01em;
}
</style>
