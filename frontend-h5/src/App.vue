<template>
  <div class="app-shell">
    <header class="topbar">
      <span class="brand">REACH</span>
      <span class="product">Part Finder</span>
    </header>
    <router-view />
  </div>
</template>

<style scoped>
.app-shell {
  min-height: 100dvh;
  background: #f3f5f8;
}

.topbar {
  position: sticky;
  top: 0;
  z-index: 30;
  display: flex;
  align-items: center;
  gap: 12px;
  height: 56px;
  padding: 0 16px;
  background: #0b1b33;
  color: #fff;
}

.brand {
  font-weight: 800;
  letter-spacing: 0.08em;
  font-size: 18px;
}

.product {
  font-size: 14px;
  opacity: 0.86;
}
</style>
