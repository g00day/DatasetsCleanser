<script setup>
import Sidebar from '../components/workspace/Sidebar.vue'
</script>

<template>
  <div class="workspace-layout">
    <header class="workspace-header">
      DatasetsCleanser
    </header>

    <div class="workspace-body">
      <Sidebar />

      <main class="workspace-content">
        <slot />
      </main>
    </div>
  </div>
</template>