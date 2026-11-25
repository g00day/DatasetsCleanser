<script setup>
import AuthLayout from '../../layouts/AuthLayout.vue'
import AccountForm from '../../components/auth/AccountForm.vue'
</script>

<template>
  <AuthLayout>
    <h1>Восстановление пароля</h1>
    <AccountForm mode="forgot" />
  </AuthLayout>
</template>
