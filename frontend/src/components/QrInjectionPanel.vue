<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Activity,
  Beaker,
  CheckCircle2,
  Circle,
  Crop,
  ImageUp,
  LoaderCircle,
  MonitorUp,
  Play,
  ScanLine,
  Square,
  XCircle,
} from 'lucide-vue-next'
import { BinaryBitmap, HybridBinarizer, QRCodeReader, RGBLuminanceSource } from '@zxing/library'
import jsQR from 'jsqr'
import { api } from '../api'
import type { CameraInjectionStatus, Device } from '../types'

const props = defineProps<{ device: Device }>()

const captureDialog = ref(false)
const video = ref<HTMLVideoElement | null>(null)
const captureSurface = ref<HTMLElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const qrBlob = ref<Blob | null>(null)
const qrDecoded = ref<{ text: string; version: number; dataBase64: string } | null>(null)
const qrUrl = ref('')
const stream = ref<MediaStream | null>(null)
const startingMode = ref<'live' | 'demo' | null>(null)
const stopping = ref(false)
const status = ref<CameraInjectionStatus | null>(null)
const dragging = ref(false)
const dragStart = reactive({ x: 0, y: 0 })
const selection = reactive({ x: 0, y: 0, width: 0, height: 0 })
let pollTimer: number | null = null

const active = computed(() => ['connecting', 'attaching', 'waiting-camera', 'injecting'].includes(status.value?.status ?? ''))
const statusLabel = computed(() => {
  const labels: Record<string, string> = {
    idle: '未启动',
    connecting: '连接中',
    attaching: '附加中',
    'waiting-camera': '等待摄像头',
    injecting: '虚拟相机运行中',
    stopped: '已停止',
    timeout: '已超时',
    failed: '失败',
  }
  return labels[status.value?.status ?? 'idle'] ?? '未知'
})

const selectionStyle = computed(() => ({
  left: `${selection.x}px`,
  top: `${selection.y}px`,
  width: `${selection.width}px`,
  height: `${selection.height}px`,
}))

const metadataSteps = computed(() => {
  const current = status.value
  if (current?.delegate_class === 'IOSMaxVirtualCamera') {
    return [
      { key: 'qr-ready', label: '二维码解析', done: current.qr_parsed === true },
      { key: 'camera-source', label: '底层相机源', done: current.metadata_stage.startsWith('camera-source') },
      { key: 'frames', label: '相机帧输出', done: current.frames_replaced > 0 },
      { key: 'scanning', label: 'WhatsApp 扫描', done: current.frames_replaced > 0 },
      { key: 'accepted', label: '接受关联', done: Boolean(current.qr_accepted) },
    ]
  }
  return [
    { key: 'qr-ready', label: '二维码解析', done: current?.qr_parsed !== null && current?.qr_parsed !== undefined },
    { key: 'controller-captured', label: '相机控制器', done: Boolean(current?.controller_class) },
    { key: 'metadata-dispatched', label: 'Metadata 提交', done: Boolean(current?.qr_dispatched) },
    {
      key: 'validating',
      label: 'WhatsApp 校验',
      done: current?.metadata_stage === 'validating' || Boolean(current?.qr_accepted),
    },
    { key: 'accepted', label: '接受关联', done: Boolean(current?.qr_accepted) },
  ]
})

const recentMetadataEvents = computed(() =>
  [...(status.value?.metadata_events ?? [])].reverse().slice(0, 8),
)

function metadataStepState(index: number) {
  if (status.value?.status === 'failed' || status.value?.status === 'timeout') {
    const firstPending = metadataSteps.value.findIndex((step) => !step.done)
    if (index === firstPending) return 'error'
  }
  if (metadataSteps.value[index].done) return 'done'
  const firstPending = metadataSteps.value.findIndex((step) => !step.done)
  if (active.value && index === firstPending) return 'active'
  return 'pending'
}

function formatEventTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date(value))
}

onMounted(() => {
  void fetchStatus()
  pollTimer = window.setInterval(fetchStatus, 500)
})

watch(() => props.device.id, () => {
  clearPreview()
  void fetchStatus()
})

onBeforeUnmount(() => {
  stopCapture()
  clearPreview()
  if (pollTimer !== null) window.clearInterval(pollTimer)
})

async function fetchStatus() {
  try {
    status.value = await api.get<CameraInjectionStatus>(`/api/devices/${props.device.id}/camera-injection`)
  } catch {
    // A device switch can race an in-flight poll.
  }
}

async function startCapture() {
  if (!navigator.mediaDevices?.getDisplayMedia) {
    ElMessage.error('当前浏览器不支持窗口捕获，请使用最新版 Edge 或 Chrome')
    return
  }
  try {
    stream.value = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false })
    captureDialog.value = true
    await nextTick()
    if (!video.value) return
    video.value.srcObject = stream.value
    await video.value.play()
    await waitForVideoFrame(video.value)
    await waitForLayout()
    initializeSelection()
    stream.value.getVideoTracks()[0]?.addEventListener('ended', () => {
      if (!qrBlob.value) captureDialog.value = false
      stopCapture()
    }, { once: true })
  } catch (error) {
    if ((error as DOMException).name !== 'NotAllowedError') {
      ElMessage.error(error instanceof Error ? error.message : '窗口捕获失败')
    }
    stopCapture()
  }
}

function waitForLayout() {
  return new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
  })
}

function waitForVideoFrame(player: HTMLVideoElement) {
  if (player.videoWidth > 0 && player.videoHeight > 0 && player.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
    return Promise.resolve()
  }
  return new Promise<void>((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      cleanup()
      reject(new Error('共享画面尚未就绪，请重新选择窗口'))
    }, 5000)
    const ready = () => {
      if (player.videoWidth <= 0 || player.videoHeight <= 0) return
      cleanup()
      if ('requestVideoFrameCallback' in player) {
        player.requestVideoFrameCallback(() => resolve())
      } else {
        requestAnimationFrame(() => resolve())
      }
    }
    const cleanup = () => {
      window.clearTimeout(timeout)
      player.removeEventListener('loadeddata', ready)
      player.removeEventListener('resize', ready)
    }
    player.addEventListener('loadeddata', ready)
    player.addEventListener('resize', ready)
    ready()
  })
}

function initializeSelection() {
  const surface = captureSurface.value
  const player = video.value
  if (!surface || !player || player.videoWidth <= 0 || player.videoHeight <= 0) return
  const display = displayedVideoRect(player, surface)
  const side = Math.min(display.width, display.height) * 0.45
  selection.x = display.x + (display.width - side) / 2
  selection.y = display.y + (display.height - side) / 2
  selection.width = side
  selection.height = side
}

function pointerPosition(event: PointerEvent) {
  const rect = captureSurface.value!.getBoundingClientRect()
  return {
    x: Math.max(0, Math.min(rect.width, event.clientX - rect.left)),
    y: Math.max(0, Math.min(rect.height, event.clientY - rect.top)),
  }
}

function beginSelection(event: PointerEvent) {
  if (!captureSurface.value) return
  const point = pointerPosition(event)
  dragging.value = true
  dragStart.x = point.x
  dragStart.y = point.y
  selection.x = point.x
  selection.y = point.y
  selection.width = 0
  selection.height = 0
  captureSurface.value.setPointerCapture(event.pointerId)
}

function updateSelection(event: PointerEvent) {
  if (!dragging.value || !captureSurface.value) return
  const point = pointerPosition(event)
  selection.x = Math.min(dragStart.x, point.x)
  selection.y = Math.min(dragStart.y, point.y)
  selection.width = Math.abs(point.x - dragStart.x)
  selection.height = Math.abs(point.y - dragStart.y)
}

function endSelection(event: PointerEvent) {
  dragging.value = false
  captureSurface.value?.releasePointerCapture(event.pointerId)
}

function displayedVideoRect(player: HTMLVideoElement, surface: HTMLElement) {
  if (
    player.videoWidth <= 0 ||
    player.videoHeight <= 0 ||
    surface.clientWidth <= 0 ||
    surface.clientHeight <= 0
  ) {
    throw new Error('共享画面尺寸无效，请重新选择窗口')
  }
  const scale = Math.min(surface.clientWidth / player.videoWidth, surface.clientHeight / player.videoHeight)
  const width = player.videoWidth * scale
  const height = player.videoHeight * scale
  return {
    x: (surface.clientWidth - width) / 2,
    y: (surface.clientHeight - height) / 2,
    width,
    height,
    scale,
  }
}

async function cropSelection() {
  const player = video.value
  const surface = captureSurface.value
  if (!player || !surface || selection.width < 32 || selection.height < 32) {
    ElMessage.warning('请框选完整二维码区域')
    return
  }
  try {
    await waitForVideoFrame(player)
    const display = displayedVideoRect(player, surface)
    const left = Math.max(selection.x, display.x)
    const top = Math.max(selection.y, display.y)
    const right = Math.min(selection.x + selection.width, display.x + display.width)
    const bottom = Math.min(selection.y + selection.height, display.y + display.height)
    if (right - left < 32 || bottom - top < 32) {
      ElMessage.warning('框选区域没有覆盖有效画面')
      return
    }
    const sourceX = Math.max(0, Math.floor((left - display.x) / display.scale))
    const sourceY = Math.max(0, Math.floor((top - display.y) / display.scale))
    const sourceWidth = Math.min(
      player.videoWidth - sourceX,
      Math.max(1, Math.ceil((right - left) / display.scale)),
    )
    const sourceHeight = Math.min(
      player.videoHeight - sourceY,
      Math.max(1, Math.ceil((bottom - top) / display.scale)),
    )
    if (sourceWidth < 32 || sourceHeight < 32) throw new Error('二维码裁剪区域太小')
    const canvas = document.createElement('canvas')
    canvas.width = sourceWidth
    canvas.height = sourceHeight
    const context = canvas.getContext('2d', { alpha: false })
    if (!context) throw new Error('浏览器无法创建截图画布')
    context.drawImage(
      player,
      sourceX,
      sourceY,
      sourceWidth,
      sourceHeight,
      0,
      0,
      sourceWidth,
      sourceHeight,
    )
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png'))
    canvas.width = 1
    canvas.height = 1
    if (!blob || blob.size === 0) throw new Error('浏览器没有生成有效 PNG')
    await setPreview(blob)
    captureDialog.value = false
    stopCapture()
  } catch (error) {
    ElMessage.error(error instanceof Error ? `二维码截取失败：${error.message}` : '二维码截取失败')
  }
}

function chooseFile() {
  fileInput.value?.click()
}

async function fileSelected(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (file.type !== 'image/png') {
    ElMessage.warning('请选择 PNG 图片')
    return
  }
  try {
    await setPreview(file)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '二维码解析失败')
  }
}

function bytesToBase64(bytes: ArrayLike<number>) {
  let binary = ''
  for (let offset = 0; offset < bytes.length; offset += 8192) {
    const end = Math.min(offset + 8192, bytes.length)
    const chunk: number[] = []
    for (let index = offset; index < end; index += 1) chunk.push(bytes[index])
    binary += String.fromCharCode(...chunk)
  }
  return btoa(binary)
}

function decodeCorrectedPayload(pixels: ImageData) {
  const luminances = new Uint8ClampedArray(pixels.width * pixels.height)
  for (let source = 0, target = 0; source < pixels.data.length; source += 4, target += 1) {
    luminances[target] = Math.round(
      (pixels.data[source] + pixels.data[source + 1] * 2 + pixels.data[source + 2]) / 4,
    )
  }
  const source = new RGBLuminanceSource(luminances, pixels.width, pixels.height)
  const reader = new QRCodeReader()
  try {
    return reader.decode(new BinaryBitmap(new HybridBinarizer(source)))
  } catch {
    return reader.decode(new BinaryBitmap(new HybridBinarizer(source.invert())))
  }
}

async function decodeQr(blob: Blob) {
  const bitmap = await createImageBitmap(blob)
  try {
    const canvas = document.createElement('canvas')
    canvas.width = bitmap.width
    canvas.height = bitmap.height
    const context = canvas.getContext('2d', { alpha: false, willReadFrequently: true })
    if (!context) throw new Error('浏览器无法读取二维码图片')
    context.drawImage(bitmap, 0, 0)
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height)
    const decoded = jsQR(pixels.data, pixels.width, pixels.height, {
      inversionAttempts: 'attemptBoth',
    })
    canvas.width = 1
    canvas.height = 1
    if (!decoded || !decoded.data || decoded.binaryData.length === 0) {
      throw new Error('未识别到完整二维码，请重新框选并保留二维码四周空白')
    }
    if (decoded.version < 1 || decoded.version > 40) {
      throw new Error('二维码版本无效')
    }
    const corrected = decodeCorrectedPayload(pixels)
    if (corrected.getText() !== decoded.data) {
      throw new Error('两次二维码解析结果不一致，请重新截取清晰的完整二维码')
    }
    const correctedData = corrected.getRawBytes()
    if (!correctedData || correctedData.length === 0) {
      throw new Error('无法提取二维码纠错数据')
    }
    return {
      text: decoded.data,
      version: decoded.version,
      dataBase64: bytesToBase64(correctedData),
    }
  } finally {
    bitmap.close()
  }
}

async function setPreview(blob: Blob) {
  const decoded = await decodeQr(blob)
  if (qrUrl.value) URL.revokeObjectURL(qrUrl.value)
  qrBlob.value = blob
  qrDecoded.value = decoded
  qrUrl.value = URL.createObjectURL(blob)
  ElMessage.success(`二维码识别成功（版本 ${decoded.version}）`)
}

function clearPreview() {
  if (qrUrl.value) URL.revokeObjectURL(qrUrl.value)
  qrUrl.value = ''
  qrBlob.value = null
  qrDecoded.value = null
}

function stopCapture() {
  stream.value?.getTracks().forEach((track) => track.stop())
  stream.value = null
  if (video.value) video.value.srcObject = null
}

async function startInjection(demo: boolean) {
  if (!qrBlob.value || !qrDecoded.value) {
    ElMessage.warning('请先抓取或上传二维码 PNG')
    return
  }
  startingMode.value = demo ? 'demo' : 'live'
  try {
    const form = new FormData()
    form.append('image', qrBlob.value, 'whatsapp-link-qr.png')
    form.append('qr_text', qrDecoded.value.text)
    form.append('qr_version', String(qrDecoded.value.version))
    form.append('qr_data_base64', qrDecoded.value.dataBase64)
    form.append('timeout_seconds', '60')
    form.append('demo', String(demo))
    const response = await fetch(`/api/devices/${props.device.id}/camera-injection`, {
      method: 'POST',
      credentials: 'same-origin',
      body: form,
    })
    const body = await response.json().catch(() => null)
    if (!response.ok) throw new Error(body?.detail || '启动注入失败')
    status.value = body as CameraInjectionStatus
    ElMessage.success(demo ? '本地反馈演示已启动' : '二维码已发送，等待手机端摄像头')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '启动注入失败')
    await fetchStatus()
  } finally {
    startingMode.value = null
  }
}

async function stopInjection() {
  stopping.value = true
  try {
    status.value = await api.delete<CameraInjectionStatus>(`/api/devices/${props.device.id}/camera-injection`)
    ElMessage.success('二维码注入已停止')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '停止失败')
  } finally {
    stopping.value = false
  }
}
</script>

<template>
  <section class="qr-panel">
    <header class="section-toolbar">
      <div>
        <h2>WhatsApp 二维码</h2>
        <span :class="['injection-state', status?.status]">{{ statusLabel }}</span>
      </div>
      <div class="qr-actions">
        <input ref="fileInput" type="file" accept="image/png" hidden @change="fileSelected" />
        <el-button @click="startCapture"><MonitorUp :size="17" />捕获窗口</el-button>
        <el-button @click="chooseFile"><ImageUp :size="17" />上传 PNG</el-button>
        <el-button :disabled="!qrBlob || active" :loading="startingMode === 'demo'" @click="startInjection(true)">
          <Beaker :size="17" />演示反馈
        </el-button>
        <el-button type="primary" :disabled="!qrBlob || active" :loading="startingMode === 'live'" @click="startInjection(false)">
          <Play :size="17" />启动虚拟相机
        </el-button>
        <el-button :disabled="!active" :loading="stopping" @click="stopInjection">
          <Square :size="16" />停止
        </el-button>
      </div>
    </header>
    <div class="qr-panel-body">
      <div class="qr-preview">
        <img v-if="qrUrl" :src="qrUrl" alt="待注入二维码预览" />
        <ScanLine v-else :size="30" />
      </div>
      <dl class="injection-details">
        <div><dt>状态</dt><dd>{{ status?.message ?? '未启动' }}</dd></div>
        <div><dt>数据源</dt><dd>{{ status?.delegate_class ?? '待检测' }}</dd></div>
        <div><dt>替换帧</dt><dd>{{ status?.frames_replaced ?? 0 }}</dd></div>
        <div><dt>WhatsApp</dt><dd>{{ status?.app_version ?? '连接后读取' }}</dd></div>
      </dl>
    </div>
    <section class="metadata-monitor" aria-label="WhatsApp 相机源监控">
      <header>
        <div><Activity :size="16" /><h3>相机源实时监控</h3></div>
        <span>{{ status?.metadata_stage ?? 'idle' }}</span>
      </header>
      <ol class="metadata-steps">
        <li
          v-for="(step, index) in metadataSteps"
          :key="step.key"
          :class="metadataStepState(index)"
        >
          <CheckCircle2 v-if="metadataStepState(index) === 'done'" :size="16" />
          <LoaderCircle v-else-if="metadataStepState(index) === 'active'" :size="16" />
          <XCircle v-else-if="metadataStepState(index) === 'error'" :size="16" />
          <Circle v-else :size="16" />
          <span>{{ step.label }}</span>
        </li>
      </ol>
      <dl class="metadata-facts">
        <div><dt>解析</dt><dd>{{ status?.qr_parsed == null ? '等待' : status.qr_parsed ? '原生通过' : '兼容模式' }}</dd></div>
        <div><dt>QR 数据</dt><dd>{{ status?.qr_version ? `V${status.qr_version} / ${status.qr_data_length} B` : '等待' }}</dd></div>
        <div><dt>Metadata Output</dt><dd>{{ status?.metadata_output_found == null ? '等待' : status.metadata_output_found ? '已定位' : '未定位' }}</dd></div>
        <div><dt>Controller</dt><dd>{{ status?.controller_class ?? '等待' }}</dd></div>
      </dl>
      <ol v-if="recentMetadataEvents.length" class="metadata-events">
        <li v-for="event in recentMetadataEvents" :key="`${event.timestamp}-${event.stage}`">
          <time :datetime="event.timestamp">{{ formatEventTime(event.timestamp) }}</time>
          <span>{{ event.message }}</span>
        </li>
      </ol>
      <div v-else class="metadata-empty">暂无相机源事件</div>
    </section>
  </section>

  <el-dialog
    v-model="captureDialog"
    title="框选 WhatsApp 关联二维码"
    width="min(920px, calc(100vw - 28px))"
    class="capture-dialog"
    @closed="stopCapture"
  >
    <div
      ref="captureSurface"
      class="capture-surface"
      @pointerdown="beginSelection"
      @pointermove="updateSelection"
      @pointerup="endSelection"
      @pointercancel="endSelection"
    >
      <video ref="video" muted playsinline />
      <div class="capture-shade" />
      <div class="capture-selection" :style="selectionStyle"><span /></div>
    </div>
    <template #footer>
      <el-button @click="captureDialog = false">取消</el-button>
      <el-button type="primary" @click="cropSelection"><Crop :size="17" />确认截取</el-button>
    </template>
  </el-dialog>
</template>
