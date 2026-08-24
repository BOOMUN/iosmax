# iOSMax 越狱安装包（Windows）

本包固定使用 **Dopamine 3.0.7** 与 **Sideloadly 0.60.0**，用于复现已经完成
验收的 Dopamine rootless 部署。它不适用于 RootHide，两个越狱环境的安装包、
端口和设备档案不得混用。

## 安装前

1. 只在你拥有或获得明确授权的设备上操作，并先备份重要数据。
2. 确认设备与 iOS 版本属于 Dopamine 官方支持范围。
3. Windows 应使用 Apple 官网版本的 iTunes 与 iCloud，不要使用 Microsoft Store 版。
4. 使用 USB 连接手机，解锁并点击“信任此电脑”。

## 使用 Sideloadly 安装 Dopamine

1. 运行 `SideloadlySetup64-0.60.0.exe` 完成安装。
2. 打开 Sideloadly，确认顶部设备列表已识别目标 iPhone。
3. 将 `Dopamine-3.0.7.ipa` 拖入 Sideloadly。
4. 输入用于签名的 Apple ID，点击 **Start**；密码和二次验证码只输入官方登录窗口，
   不要写入 iOSMax、截图、日志或聊天记录。
5. 安装完成后，在 iPhone 的“设置 → 通用 → VPN 与设备管理”中信任对应开发者。
6. 如系统要求，开启“设置 → 隐私与安全性 → 开发者模式”并按提示重启。

## 执行 Dopamine 越狱

1. 打开 Dopamine，选择 Sileo，保持 rootless 配置。
2. 点击 Jailbreak，等待设备完成重启或用户空间重启。
3. 打开 Sileo，刷新软件源，再安装 iOSMax 所需的 OpenSSH、TrollVNC、Frida 和
   Tailscale。Tailscale 是正式无线部署的必做项。
4. 越狱完成后不要升级 iOS；重启手机后通常需要再次打开 Dopamine 执行越狱。

## 安全软件提示

Dopamine 为实现越狱而包含真实的系统漏洞利用组件。Microsoft Defender 可能将 IPA 内的
`kfd`、`Vortex`、`WeightBufs` 等组件识别为 `Exploit:MacOS/*`；这不能被当作普通应用的
“无风险”扫描结果。只有在文件 SHA-256 与本说明完全一致、设备属于你或已获明确授权，
并且你理解越狱风险时才继续。不要为安装而永久关闭安全软件，也不要为其他哈希的文件
添加排除项。当前 Sideloadly 安装器的单文件 Defender 扫描未发现威胁，但它没有
Authenticode 签名，仍须通过下方哈希验证来源。

## 完整性校验

解压后在 PowerShell 中执行：

```powershell
Get-FileHash .\Dopamine-3.0.7.ipa -Algorithm SHA256
Get-FileHash .\SideloadlySetup64-0.60.0.exe -Algorithm SHA256
```

结果必须与 `SHA256SUMS.txt` 完全一致。Sideloadly 0.60.0 安装器没有
Authenticode 签名，任何哈希变化都应视为拒绝安装的条件。

官方来源：

- Dopamine：https://github.com/opa334/Dopamine/releases/tag/3.0.7
- Sideloadly：https://sideloadly.io/
