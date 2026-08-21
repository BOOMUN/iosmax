export interface User {
  id: number
  username: string
  must_change_password: boolean
}

export type JailbreakType = 'rootless' | 'roothide'

export interface Device {
  id: number
  name: string
  host: string
  ssh_port: number
  ssh_username: string
  vnc_port: number
  frida_port: number
  jailbreak_type: JailbreakType
  enabled: boolean
  notes: string
  has_ssh_password: boolean
  has_vnc_password: boolean
  created_at: string
  updated_at: string
}

export interface PortStatus {
  port: number
  reachable: boolean
  latency_ms: number | null
  error: string | null
}

export interface DeviceProbe {
  device_id: number
  checked_at: string
  ssh: PortStatus
  vnc: PortStatus
  frida: PortStatus
  jailbreak: JailbreakProbe
}

export interface JailbreakProbe {
  configured: JailbreakType
  detected: JailbreakType | null
  matches: boolean | null
  jbroot: string | null
  error: string | null
  package_version: string | null
  package_architecture: string | null
  package_filename: string | null
}

export interface DevicePayload {
  name: string
  host: string
  ssh_port: number
  ssh_username: string
  ssh_password?: string
  vnc_port: number
  vnc_password?: string
  frida_port: number
  jailbreak_type: JailbreakType
  enabled: boolean
  notes: string
}

export interface CameraInjectionStatus {
  device_id: number
  status: 'idle' | 'connecting' | 'attaching' | 'waiting-camera' | 'injecting' | 'stopped' | 'timeout' | 'failed'
  message: string
  started_at: string | null
  expires_at: string | null
  delegate_class: string | null
  frames_replaced: number
  app_version: string | null
  metadata_stage: string
  metadata_output_found: boolean | null
  controller_class: string | null
  qr_parsed: boolean | null
  qr_version: number | null
  qr_data_length: number
  qr_dispatched: boolean
  qr_accepted: boolean
  metadata_events: CameraMetadataEvent[]
}

export interface CameraMetadataEvent {
  stage: string
  message: string
  timestamp: string
  details: Record<string, string | number | boolean | null>
}
