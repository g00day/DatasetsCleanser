<script setup>
import AuthLayout from '../../layouts/AuthLayout.vue'
import AccountForm from '../../components/auth/AccountForm.vue'
</script>

<template>
  <AuthLayout>
    <h1>Новый пароль</h1>
    <AccountForm mode="reset" />
  </AuthLayout>
</template>
