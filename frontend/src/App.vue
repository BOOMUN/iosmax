<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from './api'
import type { User } from './types'
import LoginView from './components/LoginView.vue'
import DashboardView from './components/DashboardView.vue'

const user = ref<User | null | undefined>(undefined)

onMounted(async () => {
  try {
    user.value = await api.get<User>('/api/auth/me')
  } catch {
    user.value = null
  }
})

async function logout() {
  await api.post('/api/auth/logout')
  user.value = null
}
</script>

<template>
  <div v-if="user === undefined" class="boot-screen">
    <div class="boot-mark">iM</div>
  </div>
  <LoginView v-else-if="user === null" @authenticated="user = $event" />
  <DashboardView v-else :user="user" @user-updated="user = $event" @logout="logout" />
</template>

