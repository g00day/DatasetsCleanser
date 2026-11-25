<script setup>
import AuthLayout from '../../layouts/AuthLayout.vue'
import AccountForm from '../../components/auth/AccountForm.vue'
</script>

<template>
  <AuthLayout>
    <h1>Регистрация</h1>
    <AccountForm mode="register" />
  </AuthLayout>
</template>
