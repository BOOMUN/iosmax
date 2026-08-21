<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  CirclePlus,
  House,
  LoaderCircle,
  LogOut,
  MoreVertical,
  Pencil,
  Power,
  RefreshCw,
  ShieldCheck,
  Smartphone,
  Trash2,
  Wifi,
} from 'lucide-vue-next'
import { api } from '../api'
import type { Device, DeviceProbe, User } from '../types'
import DeviceDialog from './DeviceDialog.vue'
import QrInjectionPanel from './QrInjectionPanel.vue'
import VncViewer from './VncViewer.vue'

const props = defineProps<{ user: User }>()
const emit = defineEmits<{ logout: []; 'user-updated': [user: User] }>()

const devices = ref<Device[]>([])
const selectedId = ref<number | null>(null)
const probe = ref<DeviceProbe | null>(null)
const probing = ref(false)
const dialogOpen = ref(false)
const editing = ref<Device | null>(null)
const passwordDialog = ref(props.user.must_change_password)
const currentPassword = ref('')
const newPassword = ref('')
const changingPassword = ref(false)
const systemActionPending = ref<'wake' | 'home' | null>(null)

const selected = computed(() => devices.value.find((item) => item.id === selectedId.value) ?? null)
const online = computed(() => Boolean(probe.value?.ssh.reachable || probe.value?.vnc.reachable || probe.value?.frida.reachable))

onMounted(loadDevices)

async function loadDevices() {
  try {
    devices.value = await api.get<Device[]>('/api/devices')
    if (selectedId.value === null && devices.value.length) selectedId.value = devices.value[0].id
    if (selected.value) await runProbe()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '设备加载失败')
  }
}

async function runProbe() {
  if (!selected.value) return
  probing.value = true
  try {
    probe.value = await api.post<DeviceProbe>(`/api/devices/${selected.value.id}/probe`)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '检测失败')
  } finally {
    probing.value = false
  }
}

async function selectDevice(device: Device) {
  selectedId.value = device.id
  probe.value = null
  await runProbe()
}

function addDevice() {
  editing.value = null
  dialogOpen.value = true
}

function editDevice() {
  if (!selected.value) return
  editing.value = selected.value
  dialogOpen.value = true
}

function savedDevice(device: Device) {
  const index = devices.value.findIndex((item) => item.id === device.id)
  if (index >= 0) devices.value[index] = device
  else devices.value.push(device)
  devices.value.sort((a, b) => a.name.localeCompare(b.name))
  selectedId.value = device.id
  void runProbe()
}

async function removeDevice() {
  if (!selected.value) return
  await ElMessageBox.confirm(`删除设备“${selected.value.name}”？`, '删除设备', {
    confirmButtonText: '删除',
    cancelButtonText: '取消',
    type: 'warning',
  })
  await api.delete(`/api/devices/${selected.value.id}`)
  selectedId.value = null
  probe.value = null
  await loadDevices()
  ElMessage.success('设备已删除')
}

async function systemAction(action: 'wake' | 'home') {
  if (!selected.value) return
  systemActionPending.value = action
  try {
    const result = await api.post<{ success: boolean; message: string }>(
      `/api/devices/${selected.value.id}/system`,
      { action },
    )
    ElMessage.success(result.message)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '操作失败')
  } finally {
    systemActionPending.value = null
  }
}

async function changePassword() {
  changingPassword.value = true
  try {
    const updated = await api.post<User>('/api/auth/change-password', {
      current_password: currentPassword.value,
      new_password: newPassword.value,
    })
    emit('user-updated', updated)
    passwordDialog.value = false
    currentPassword.value = ''
    newPassword.value = ''
    ElMessage.success('管理员密码已更新')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '密码修改失败')
  } finally {
    changingPassword.value = false
  }
}

function portClass(reachable?: boolean) {
  return reachable ? 'port-up' : 'port-down'
}

function jailbreakLabel(type?: Device['jailbreak_type'] | null) {
  if (type === 'roothide') return 'RootHide'
  if (type === 'rootless') return 'Rootless'
  return '未检测'
}
</script>

<template>
  <div class="app-shell">
    <aside class="device-sidebar">
      <header class="sidebar-brand">
        <div class="brand-mark small">iM</div>
        <div><strong>iOSMax</strong><span>Control</span></div>
      </header>
      <div class="sidebar-heading">
        <span>设备</span>
        <el-tooltip content="添加设备" placement="right">
          <button class="icon-button" @click="addDevice"><CirclePlus :size="18" /></button>
        </el-tooltip>
      </div>
      <nav class="device-list">
        <button
          v-for="device in devices"
          :key="device.id"
          :class="['device-row', { active: device.id === selectedId }]"
          @click="selectDevice(device)"
        >
          <Smartphone :size="19" />
          <span><strong>{{ device.name }}</strong><small>{{ device.host }} · {{ jailbreakLabel(device.jailbreak_type) }}</small></span>
          <i :class="device.id === selectedId && online ? 'online' : ''" />
        </button>
        <button v-if="!devices.length" class="empty-device" @click="addDevice">
          <CirclePlus :size="20" />
          添加第一台设备
        </button>
      </nav>
      <footer class="sidebar-footer">
        <button @click="passwordDialog = true"><ShieldCheck :size="17" />账号安全</button>
        <button @click="emit('logout')"><LogOut :size="17" />退出</button>
      </footer>
    </aside>

    <main class="workspace">
      <template v-if="selected">
        <header class="workspace-header">
          <div>
            <div class="device-title-line">
              <h1>{{ selected.name }}</h1>
              <span :class="['device-status', online ? 'online' : 'offline']">{{ online ? '在线' : '离线' }}</span>
              <span :class="['jailbreak-badge', selected.jailbreak_type]">{{ jailbreakLabel(selected.jailbreak_type) }}</span>
            </div>
            <p>{{ selected.host }}</p>
          </div>
          <div class="header-actions">
            <el-button :loading="probing" @click="runProbe"><RefreshCw :size="17" />刷新状态</el-button>
            <el-dropdown trigger="click">
              <el-button circle><MoreVertical :size="18" /></el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item @click="editDevice"><Pencil :size="15" />编辑设备</el-dropdown-item>
                  <el-dropdown-item divided @click="removeDevice"><Trash2 :size="15" />删除设备</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </header>

        <section class="status-band">
          <div><Wifi :size="18" /><span>SSH</span><strong :class="portClass(probe?.ssh.reachable)">{{ probe?.ssh.reachable ? `${probe.ssh.latency_ms} ms` : '不可达' }}</strong><small>:{{ selected.ssh_port }}</small></div>
          <div><Wifi :size="18" /><span>TrollVNC</span><strong :class="portClass(probe?.vnc.reachable)">{{ probe?.vnc.reachable ? `${probe.vnc.latency_ms} ms` : '不可达' }}</strong><small>:{{ selected.vnc_port }}</small></div>
          <div><Wifi :size="18" /><span>Frida</span><strong :class="portClass(probe?.frida.reachable)">{{ probe?.frida.reachable ? `${probe.frida.latency_ms} ms` : '不可达' }}</strong><small>:{{ selected.frida_port }}</small></div>
          <div>
            <ShieldCheck :size="18" />
            <span>越狱环境</span>
            <strong :class="probe?.jailbreak.matches === false ? 'port-down' : 'port-up'">
              {{ jailbreakLabel(probe?.jailbreak.detected ?? selected.jailbreak_type) }}
            </strong>
            <small>{{ probe?.jailbreak.matches === false
              ? '配置不匹配'
              : probe?.jailbreak.package_version ?? (probe?.jailbreak.detected ? '已验证' : '待检测') }}</small>
          </div>
        </section>

        <section class="quick-actions">
          <header><h2>系统控制</h2></header>
          <div class="system-action-grid">
            <button
              class="system-action-button"
              :disabled="systemActionPending !== null"
              title="唤醒屏幕"
              @click="systemAction('wake')"
            >
              <LoaderCircle v-if="systemActionPending === 'wake'" class="action-spinner" :size="20" />
              <Power v-else :size="20" />
              <span>唤醒屏幕</span>
            </button>
            <button
              class="system-action-button"
              :disabled="systemActionPending !== null"
              title="返回桌面"
              @click="systemAction('home')"
            >
              <LoaderCircle v-if="systemActionPending === 'home'" class="action-spinner" :size="20" />
              <House v-else :size="20" />
              <span>返回桌面</span>
            </button>
          </div>
        </section>

        <el-alert
          v-if="probe?.jailbreak.matches === false"
          title="越狱类型不匹配，已禁止虚拟摄像头注入"
          :description="`配置为 ${jailbreakLabel(selected.jailbreak_type)}，实际检测为 ${jailbreakLabel(probe.jailbreak.detected)}。请先编辑设备类型。`"
          type="error"
          :closable="false"
          show-icon
        />
        <QrInjectionPanel v-else :device="selected" />
        <VncViewer :device="selected" />
      </template>

      <section v-else class="empty-workspace">
        <Smartphone :size="34" />
        <h1>尚未添加设备</h1>
        <el-button type="primary" @click="addDevice"><CirclePlus :size="17" />添加设备</el-button>
      </section>
    </main>

    <DeviceDialog :open="dialogOpen" :device="editing" @close="dialogOpen = false" @saved="savedDevice" />

    <el-dialog
      v-model="passwordDialog"
      title="修改管理员密码"
      width="min(440px, calc(100vw - 32px))"
      :close-on-click-modal="!user.must_change_password"
      :show-close="!user.must_change_password"
    >
      <el-alert v-if="user.must_change_password" title="首次登录必须修改初始密码" type="warning" :closable="false" />
      <el-form label-position="top" class="password-form">
        <el-form-item label="当前密码"><el-input v-model="currentPassword" type="password" show-password /></el-form-item>
        <el-form-item label="新密码（至少 10 位）"><el-input v-model="newPassword" type="password" show-password /></el-form-item>
      </el-form>
      <template #footer>
        <el-button v-if="!user.must_change_password" @click="passwordDialog = false">取消</el-button>
        <el-button type="primary" :loading="changingPassword" @click="changePassword">更新密码</el-button>
      </template>
    </el-dialog>
  </div>
</template>
