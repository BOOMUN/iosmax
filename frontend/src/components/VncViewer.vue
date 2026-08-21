<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Expand, MonitorPlay, Power, RefreshCw } from 'lucide-vue-next'
import RFB from '@novnc/novnc'
import type { Device } from '../types'

const props = defineProps<{ device: Device }>()
const target = ref<HTMLElement | null>(null)
const password = ref('')
const state = ref<'idle' | 'connecting' | 'connected' | 'failed'>('idle')
let rfb: RFB | null = null
let connectionSequence = 0

const DISCONNECT_TIMEOUT_MS = 2500
const REMOTE_SETTLE_MS = 750

function waitForDisconnect(instance: RFB): Promise<void> {
  return new Promise((resolve) => {
    let finished = false
    const finish = () => {
      if (finished) return
      finished = true
      window.clearTimeout(timeout)
      instance.removeEventListener('disconnect', finish)
      resolve()
    }
    const timeout = window.setTimeout(finish, DISCONNECT_TIMEOUT_MS)
    instance.addEventListener('disconnect', finish)
    instance.disconnect()
  })
}

function disconnect() {
  connectionSequence += 1
  const current = rfb
  rfb = null
  current?.disconnect()
  state.value = 'idle'
  if (target.value) target.value.innerHTML = ''
}

async function connect() {
  if (state.value === 'connecting') return
  if (props.device.has_vnc_password && !password.value) {
    ElMessage.warning('请输入 TrollVNC 密码')
    return
  }

  const sequence = ++connectionSequence
  const previous = rfb
  rfb = null
  state.value = 'connecting'
  if (previous) {
    await waitForDisconnect(previous)
    await new Promise((resolve) => window.setTimeout(resolve, REMOTE_SETTLE_MS))
    if (sequence !== connectionSequence) return
  }

  if (target.value) target.value.innerHTML = ''
  await nextTick()
  if (!target.value || sequence !== connectionSequence) return
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const url = `${scheme}://${window.location.host}/ws/vnc/${props.device.id}`
  try {
    const options = password.value ? { credentials: { password: password.value } } : {}
    const instance = new RFB(target.value, url, options)
    let securityFailed = false
    rfb = instance
    instance.scaleViewport = true
    instance.resizeSession = false
    instance.qualityLevel = 7
    instance.compressionLevel = 2
    instance.addEventListener('connect', () => {
      if (rfb !== instance || sequence !== connectionSequence) return
      state.value = 'connected'
      instance.focus()
    })
    instance.addEventListener('securityfailure', (event: Event) => {
      if (rfb !== instance || sequence !== connectionSequence) return
      securityFailed = true
      state.value = 'failed'
      const reason = (event as CustomEvent<{ reason?: string }>).detail?.reason
      ElMessage.error(reason ? `TrollVNC 认证失败：${reason}` : 'TrollVNC 密码错误或认证失败')
    })
    instance.addEventListener('disconnect', (event: Event) => {
      if (rfb !== instance || sequence !== connectionSequence) return
      rfb = null
      if (securityFailed) return
      const clean = (event as CustomEvent<{ clean: boolean }>).detail?.clean
      state.value = clean ? 'idle' : 'failed'
      if (!clean) ElMessage.error('VNC 连接已断开')
    })
    instance.addEventListener('credentialsrequired', () => {
      if (rfb !== instance || sequence !== connectionSequence) return
      if (!password.value) {
        securityFailed = true
        state.value = 'failed'
        ElMessage.error('请输入 TrollVNC 密码后重新连接')
        instance.disconnect()
        return
      }
      instance.sendCredentials({ password: password.value })
    })
  } catch (error) {
    if (sequence !== connectionSequence) return
    state.value = 'failed'
    ElMessage.error(error instanceof Error ? error.message : 'VNC 连接失败')
  }
}

async function fullscreen() {
  await target.value?.requestFullscreen()
  rfb?.focus()
}

watch(() => props.device.id, () => {
  disconnect()
  password.value = ''
})
onBeforeUnmount(disconnect)
</script>

<template>
  <section class="viewer-section">
    <header class="section-toolbar">
      <div>
        <h2>实时控制</h2>
        <span :class="['connection-state', state]">
          {{ state === 'connected' ? '已连接' : state === 'connecting' ? '连接中' : state === 'failed' ? '连接失败' : '未连接' }}
        </span>
      </div>
      <div class="viewer-actions">
        <el-input
          v-model="password"
          type="password"
          show-password
          placeholder="TrollVNC 密码（USB 模式可留空）"
          class="vnc-password"
          @keyup.enter="connect"
        />
        <el-tooltip content="连接或重新连接" placement="bottom">
          <el-button type="primary" :loading="state === 'connecting'" :disabled="state === 'connecting'" @click="connect">
            <RefreshCw v-if="state !== 'idle'" :size="17" />
            <MonitorPlay v-else :size="17" />
            连接
          </el-button>
        </el-tooltip>
        <el-tooltip content="全屏" placement="bottom">
          <el-button :disabled="state !== 'connected'" circle @click="fullscreen"><Expand :size="17" /></el-button>
        </el-tooltip>
        <el-tooltip content="断开" placement="bottom">
          <el-button :disabled="state === 'idle'" circle @click="disconnect"><Power :size="17" /></el-button>
        </el-tooltip>
      </div>
    </header>
    <div class="viewer-stage">
      <div ref="target" class="vnc-target" tabindex="0" />
      <div v-if="state === 'idle'" class="viewer-empty">
        <MonitorPlay :size="28" />
        <span>{{ device.host }}:{{ device.vnc_port }}</span>
      </div>
      <div v-else-if="state === 'connecting'" class="viewer-empty viewer-loading">
        <span>正在建立安全转发...</span>
      </div>
    </div>
  </section>
</template>
