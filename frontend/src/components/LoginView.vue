<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { LockKeyhole, LogIn, UserRound } from 'lucide-vue-next'
import { api } from '../api'
import type { User } from '../types'

const emit = defineEmits<{ authenticated: [user: User] }>()
const username = ref('admin')
const password = ref('')
const loading = ref(false)

async function submit() {
  loading.value = true
  try {
    const user = await api.post<User>('/api/auth/login', {
      username: username.value,
      password: password.value,
    })
    emit('authenticated', user)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-panel" aria-label="管理员登录">
      <header class="login-brand">
        <div class="brand-mark">iM</div>
        <div>
          <h1>iOSMax Control</h1>
          <p>设备控制台</p>
        </div>
      </header>

      <form class="login-form" @submit.prevent="submit">
        <label>
          <span>管理员账号</span>
          <el-input v-model="username" size="large" autocomplete="username">
            <template #prefix><UserRound :size="18" /></template>
          </el-input>
        </label>
        <label>
          <span>密码</span>
          <el-input
            v-model="password"
            type="password"
            size="large"
            autocomplete="current-password"
            show-password
          >
            <template #prefix><LockKeyhole :size="18" /></template>
          </el-input>
        </label>
        <el-button native-type="submit" type="primary" size="large" :loading="loading">
          <LogIn :size="18" />
          登录
        </el-button>
      </form>
    </section>
  </main>
</template>
