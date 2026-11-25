<script setup>
import { provide, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import Sidebar from '../components/workspace/Sidebar.vue'
import UserMenu from '../components/workspace/UserMenu.vue'
import ProjectDialog from '../components/workspace/ProjectDialog.vue'

const route = useRoute()
const open = ref(false)
const dialog = ref(null)
const revision = ref(0)
provide('openProjectDialog', (mode, project) => { dialog.value = { mode, project } })
watch(() => route.fullPath, () => { open.value = false })
function saved() {
  dialog.value = null
  revision.value++
}
</script>

<template>
  <div class="workspace-layout">
    <header class="workspace-header">
      <button class="mobile-toggle" @click="open = !open" :aria-expanded="open">Проекты</button>
      <RouterLink class="brand" to="/home">DatasetCleanser</RouterLink>
      <UserMenu />
    </header>
    <div class="workspace-body">
      <Sidebar :key="revision" :class="{ expanded: open }" />
      <main class="workspace-content">
        <RouterView :key="route.path + revision" />
      </main>
    </div>
  </div>
  <ProjectDialog v-if="dialog" v-bind="dialog" @close="dialog = null" @saved="saved" />
</template>
