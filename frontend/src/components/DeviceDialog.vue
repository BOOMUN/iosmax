<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import type { Device, DevicePayload } from '../types'

const props = defineProps<{ open: boolean; device: Device | null }>()
const emit = defineEmits<{ close: []; saved: [device: Device] }>()

const form = reactive<DevicePayload>({
  name: '',
  host: '',
  ssh_port: 22,
  ssh_username: 'mobile',
  ssh_password: '',
  vnc_port: 5901,
  vnc_password: '',
  frida_port: 27042,
  jailbreak_type: 'rootless',
  enabled: true,
  notes: '',
})
const saving = ref(false)

watch(
  () => [props.open, props.device] as const,
  () => {
    if (!props.open) return
    Object.assign(form, {
      name: props.device?.name ?? '',
      host: props.device?.host ?? '',
      ssh_port: props.device?.ssh_port ?? 22,
      ssh_username: props.device?.ssh_username ?? 'mobile',
      ssh_password: '',
      vnc_port: props.device?.vnc_port ?? 5901,
      vnc_password: '',
      frida_port: props.device?.frida_port ?? 27042,
      jailbreak_type: props.device?.jailbreak_type ?? 'rootless',
      enabled: props.device?.enabled ?? true,
      notes: props.device?.notes ?? '',
    })
  },
  { immediate: true },
)

async function save() {
  if (!form.name.trim() || !form.host.trim()) {
    ElMessage.warning('请填写设备名称和局域网 IP 地址')
    return
  }
  saving.value = true
  try {
    const payload = { ...form }
    if (!payload.ssh_password) delete payload.ssh_password
    if (!payload.vnc_password) delete payload.vnc_password
    const device = props.device
      ? await api.patch<Device>(`/api/devices/${props.device.id}`, payload)
      : await api.post<Device>('/api/devices', payload)
    emit('saved', device)
    emit('close')
    ElMessage.success('设备配置已保存')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存失败')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="open"
    :title="device ? '编辑设备' : '添加设备'"
    width="min(560px, calc(100vw - 32px))"
    @close="emit('close')"
  >
    <el-form label-position="top" class="device-form">
      <div class="form-grid">
        <el-form-item label="设备名称">
          <el-input v-model="form.name" placeholder="本地 iPhone 12" />
        </el-form-item>
        <el-form-item label="局域网 IP / 主机名">
          <el-input v-model="form.host" placeholder="192.168.110.x" />
        </el-form-item>
        <el-form-item label="越狱类型">
          <el-select v-model="form.jailbreak_type" style="width: 100%">
            <el-option label="Rootless（Dopamine）" value="rootless" />
            <el-option label="RootHide" value="roothide" />
          </el-select>
        </el-form-item>
        <el-form-item label="SSH 用户">
          <el-input v-model="form.ssh_username" />
        </el-form-item>
        <el-form-item :label="device?.has_ssh_password ? 'SSH 密码（留空不修改）' : 'SSH 密码'">
          <el-input v-model="form.ssh_password" type="password" show-password />
        </el-form-item>
        <el-form-item label="SSH 端口">
          <el-input-number v-model="form.ssh_port" :min="1" :max="65535" controls-position="right" />
        </el-form-item>
        <el-form-item label="TrollVNC 端口">
          <el-input-number v-model="form.vnc_port" :min="1" :max="65535" controls-position="right" />
        </el-form-item>
        <el-form-item :label="device?.has_vnc_password ? 'TrollVNC 密码（留空不修改）' : 'TrollVNC 密码'">
          <el-input v-model="form.vnc_password" type="password" show-password />
        </el-form-item>
        <el-form-item label="Frida 端口">
          <el-input-number v-model="form.frida_port" :min="1" :max="65535" controls-position="right" />
        </el-form-item>
        <el-form-item label="启用设备">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </div>
      <el-alert
        :title="form.jailbreak_type === 'rootless' ? 'Rootless 安装包' : 'RootHide 安装包'"
        :description="form.jailbreak_type === 'rootless'
          ? '固定根目录 /var/jb，使用 iphoneos-arm64 / rootless 构建。'
          : '根目录由 /usr/bin/jbroot 动态解析，使用 iphoneos-arm64e / PAC00 构建。'"
        type="info"
        :closable="false"
        show-icon
      />
      <el-form-item label="备注">
        <el-input v-model="form.notes" type="textarea" :rows="3" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('close')">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>
