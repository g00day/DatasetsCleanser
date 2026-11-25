<script setup>
import { onMounted, ref } from 'vue'

defineProps({ title: String, busy: Boolean })
const emit = defineEmits(['close'])
const dialog = ref(null)
onMounted(() => dialog.value.showModal())
</script>

<template>
  <dialog ref="dialog" aria-labelledby="dialog-title" @cancel.prevent="!busy && emit('close')">
    <header>
      <h2 id="dialog-title">{{ title }}</h2>
      <button aria-label="Закрыть" :disabled="busy" @click="emit('close')">×</button>
    </header>
    <slot />
  </dialog>
</template>
