<script setup>
import AuthLayout from '../../layouts/AuthLayout.vue'
import AccountForm from '../../components/auth/AccountForm.vue'
</script>

<template>
  <AuthLayout>
    <h1>Авторизация</h1>
    <AccountForm mode="login" />
  </AuthLayout>
</template>
