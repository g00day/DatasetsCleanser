<script setup>
    defineProps({
        label: {
            type: String,
            required: true 
        },
        id: {
            type: String,
            required: true
        },
        type: {
            type: String,
            default: 'text'
        },
        placeholder: {
            type: String,
            default: ''
        }
    })

    const model = defineModel()
</script>

<template>
    <div class="auth-field">
        <label :for="id">{{label}}</label>

        <input :id="id" v-model="model" :type="type" :placeholder="placeholder"/>
    </div>
</template>
