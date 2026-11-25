<script setup>
defineProps({
  label: String,
  id: String,
  type: { type: String, default: 'text' },
  autocomplete: String,
  minlength: Number,
})
const model = defineModel()
</script>

<template>
  <div class="auth-field">
    <label :for="id">{{ label }}</label>
    <input v-model="model" :id="id" :type="type" :autocomplete="autocomplete"
      :minlength="minlength" required />
  </div>
</template>
