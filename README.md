# iOSMax Control

本地 Web 控制台，用于统一管理多台越狱 iPhone。支持管理员登录、设备管理、
SSH/VNC/Frida 连通性检测、系统唤醒、返回桌面、noVNC 实时控制，以及 WhatsApp
关联二维码虚拟摄像头任务。

## 越狱类型

每台设备必须明确保存 `jailbreak_type`，当前只允许以下两个值：

| 类型 | 常见环境 | 根目录 | 虚拟摄像头包 |
| --- | --- | --- | --- |
| `rootless` | Dopamine | `/var/jb` | `iphoneos-arm64` / rootless |
| `roothide` | RootHide | `/usr/bin/jbroot` 动态结果 | `iphoneos-arm64e` / PAC00 |

控制台探测设备时会通过 SSH 独立识别实际环境。配置值与检测值不一致时，
虚拟摄像头注入会被后端拒绝，前端同时显示红色错误提示。

权威工程与安装包严格分开：

```text
device/virtual-camera/shared/
device/virtual-camera/rootless/
device/virtual-camera/roothide/

artifacts/virtual-camera/rootless/
artifacts/virtual-camera/roothide/
```

每个产物目录都有独立 `manifest.json`。部署选择以设备类型、清单类型、
架构、包内 `X-IOSMax-Jailbreak-Type` 和 SHA-256 同时匹配为准，不从旧的
仓库级 `artifacts/` 文件名猜测类型。

## 环境

- Windows 10/11
- Python 3.10+
- Node.js 20+
- 与控制电脑可通过 USB 端口转发或同一 Tailnet 连接的越狱 iPhone
- iPhone 端 OpenSSH；远程画面和“返回桌面”依赖 TrollVNC；“唤醒屏幕”依赖 Frida

## USB 与无线连接并存

无线设备通过 `data/wireless_tunnels.json` 配置。后台只在 Windows 本机
`127.0.0.1` 建立端口，使用 iPhone 的 SSH 主机密钥与 UDID 双重校验，然后把
SSH、TrollVNC 和 Frida 转发到手机本机监听地址。TrollVNC/Frida 不直接暴露到
局域网；无线断开后后台会自动重连，并在 DHCP 地址变化时按配置网段重新发现设备。

USB 设备通过 `data/usb_tunnels.json` 固定 UDID 与本机端口。桌面快捷方式调用
`start-usb-tunnels.ps1`，只为当前已连接的设备补齐缺失的 `iproxy` 进程；已经存在
的监听必须与配置中的 UDID 和端口一致，离线设备会被跳过。每条 USB 配置也必须明确
标记 `rootless` 或 `roothide`，两类安装包和设备档案不得混用。

### Tailscale（无线部署必做）

每台新设备都必须从 App Store 安装官方 Tailscale，并与控制电脑登录同一 Tailnet。
局域网地址只用于首次安装和故障诊断，不作为无线部署完成的依据。正式无线隧道使用
设备的 Tailscale IPv4 地址（`100.x.x.x/32`），同时固定 SSH 主机密钥并校验 UDID。
TrollVNC 和 Frida 继续只监听手机回环地址，不得直接暴露到公网或局域网。

无线验收必须断开 USB，并至少确认 SSH、VNC 画面、Frida、唤醒和返回桌面均可通过
Tailnet 工作。手机切换到其他 Wi-Fi 或蜂窝网络后还应能自动重连。

iPhone X 当前端口彼此独立：

| 连接 | SSH | TrollVNC | Frida |
| --- | ---: | ---: | ---: |
| USB | 2222 | 5901 | 27043 |
| Wi-Fi（SSH 隧道） | 2223 | 5902 | 27044 |

iPhone X2 当前端口同样独立，正式无线连接固定走 Tailnet：

| 连接 | SSH | TrollVNC | Frida |
| --- | ---: | ---: | ---: |
| USB | 2225 | 5904 | 27046 |
| Tailscale（SSH 隧道） | 2226 | 5905 | 27047 |

iPhone Plus（实际机型 iPhone 11 Pro Max）使用独立的 rootless 端口：

| 连接 | SSH | TrollVNC | Frida |
| --- | ---: | ---: | ---: |
| USB | 2227 | 5906 | 27048 |
| Tailscale（SSH 隧道） | 2228 | 5907 | 27049 |

控制台中的无线设备档案应填写主机 `127.0.0.1` 和无线端口。原 USB 设备档案保持不变。

## 初始化与运行

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm.cmd --prefix frontend install
.\run.ps1
```

浏览器访问 <http://127.0.0.1:8010>。首次登录后应立即修改管理员密码。

### Windows 桌面快速启动

完成初始化后运行一次：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-web-shortcut.ps1
```

脚本会在当前用户桌面创建 `iOSMax Web` 快捷方式。双击时，如果控制台已经运行，
会直接打开网页；如果尚未运行，会在后台启动服务、等待健康检查通过后再打开
<http://127.0.0.1:8010>。重复双击不会重复启动监听 `8010` 的服务。

## 添加设备流程

1. 点击“添加设备”，填写连接地址、SSH 账号和端口。
2. 选择 `Rootless（Dopamine）` 或 `RootHide`，不要只写在备注中。
3. 从 App Store 安装 Tailscale，并与控制电脑登录同一 Tailnet。
4. 固定设备的 Tailscale IPv4、SSH 主机密钥和 UDID，建立本机 SSH 隧道。
5. 保存后执行“刷新状态”。
6. 确认“越狱环境”显示“已验证”，且配置类型等于 SSH 检测类型。
7. 仅使用该类型对应的虚拟摄像头清单和安装包。
8. 断开 USB，完成 SSH、VNC、Frida、唤醒和返回桌面验收。

已有数据库会在启动时自动增加 `jailbreak_type` 字段；历史设备迁移为
`rootless`，随后应通过 SSH 探测确认。

## WhatsApp 二维码注入

1. 在手机 WhatsApp 进入“设置 → 关联设备 → 关联设备”，保持扫码页在前台。
2. 在控制台点击“捕获窗口”并框选完整二维码，也可以上传 PNG。
3. 确认设备越狱类型已验证后，点击“启动虚拟相机”。
4. 成功、停止或超时都会写回禁用控制，二维码不会写入数据库。

虚拟摄像头仅替换路由到目标 WhatsApp PID 的相机缓冲；控制文件缺失、
图片无效、环境类型不一致或渲染异常时均按 fail-open 处理。
