<script setup>
import ProjectList from './ProjectList.vue'
</script>

<template>
  <aside class="sidebar">
    <RouterLink to="/home" class="home-btn">
      Главная
    </RouterLink>

    <ProjectList />
  </aside>
</template>