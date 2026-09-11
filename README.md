# 🎙️ VoiceSpark · 灵感闪念与语音胶囊

> **“走路、开车、洗澡时的灵光乍现，不再遗忘在空气中。”** —— 按住 iPhone 侧边操作按钮或轻点桌面，说出你的碎片想法，Gemini 10 秒内听写真实逐字稿、自动去除“那个/嗯/就是说”口头禅、提取核心要点与待办，并一键直通 **OurTodo**！

---

## 🌟 核心特色与功能亮点

1. **随说随记 · 音频多模态直传**：
   * 原生支持 Web 端直接录音（实时声波动效与计时器）、上传任意格式音频（`m4a`, `mp3`, `wav`, `webm`, `aac`）。
   * 支持通过 iOS 快捷指令（Action Button / 锁屏组件）一键长按录音并秒传后台。
2. **Gemini 3.8 Flash 深度思维整理**：
   * **逐字口播 (Raw Transcript)**：一字一句如实听写，绝不省略任何细节。
   * **去口头禅精修稿 (Polished Text)**：彻底剔除口水词与停顿，梳理语序与标点，输出排版考究的正式笔记。
   * **四维智能归类**：自动归入「💡 灵感闪念」、「✅ 待办行动」、「📖 见闻随笔」、「🧠 情绪复盘」。
   * **一句话主旨与结构化拆解**：点破核心本质，输出带层级的清晰要点。
3. **生态联动 · 直通 OurTodo PWA**：
   * 自动从语音中嗅探行动项（Action Items）。
   * 点击 **「送往 OurTodo」**，直接通过 API 推送创建协同待办，无缝打通。
4. **iPhone 锁屏 Web Push 强提醒**：
   * 集成 W3C VAPID Web Push 服务。
   * 提炼完成后手机自动亮屏弹窗：“💡 灵感已入库 · 《xxx》”，点击直接查看。
5. **iOS 18 风格极致质感 PWA**：
   * 优雅深色玻璃拟态 (Glassmorphism)，适配 iPhone 灵动岛与底部安全区域。
   * 支持一键复制完整 Markdown（完美兼容 Apple 备忘录、Notion、Obsidian）。
6. **Google Cloud Storage (GCS) 云端双向持久化**：
   * SQLite 数据库 (`voicespark.db`) 实时原子增量备份至专属云存储桶 `gs://voice-spark-data-cjlinn-471522`。
   * 原声录音音频 (`data/audio/*.mp3`) 与 Web Push 密钥 (`vapid_keys.json`) 自动云端持久化与按需拉取。
   * 彻底解决 Cloud Run 容器无状态无盘问题：跨部署、更新修订版本、容器重启数据 100% 永不丢失。

---

## 🏗️ 目录结构

```text
VoiceSpark/
├── backend/
│   ├── config.py            # 存储路径、Vertex AI / Gemini 配置、GCS 存储桶、VAPID 秘钥
│   ├── database.py          # SQLite 数据库：语音记录、分类、设置、Push 订阅与变更通知
│   ├── storage_sync.py      # Google Cloud Storage 双向持久化同步引擎 (DB原子快照/音频同步/密钥恢复)
│   ├── prestart.py          # 容器启动前置冷启动数据还原程序
│   ├── audio_processor.py   # ffmpeg 音频转码压缩、标准化与时长提取
│   ├── ai_spark.py          # Gemini 3.8 Flash 音频转写、口语精修与要点提取
│   ├── todo_sync.py         # 联动 OurTodoPWA（自动将待办推入 OurTodo）
│   ├── push_service.py      # W3C VAPID Web Push 锁屏提醒通知
│   └── main.py              # FastAPI 核心服务、REST 接口与 PWA 静态资源路由
├── static/
│   ├── index.html           # iOS 18 风格 Vue 3 + Tailwind PWA 界面（带实时声波录音与GCS云同步状态）
│   ├── manifest.json        # PWA 配置与 Web Share Target
│   ├── sw.js                # Service Worker 离线缓存与锁屏推送监听
│   ├── icons/               # 高清 PWA 图标 (192x192, 512x512, apple-touch-icon)
│   └── generate_icons.py    # 图标生成脚本 (PIL)
├── shortcuts/
│   └── ios_shortcut_guide.md# iPhone 操作按钮 / 锁屏快捷指令配置教程
├── tests/
│   ├── test_database.py     # 数据库生命周期单元测试
│   ├── test_storage_sync.py # GCS 持久化存储与音频同步单元测试
│   ├── test_audio_processor.py # 音频处理单元测试
│   ├── test_ai_spark.py     # AI 解析容错测试
│   └── test_api.py          # FastAPI REST 接口自动化集成测试
├── Dockerfile               # 包含 ffmpeg 与 Python 3.12 的生产级容器配置（支持 prestart 恢复）
├── openapi.yaml             # Google Cloud API Gateway 声明式路由定义
├── setup_gateway.sh         # 一键上云全套部署脚本 (基于 Cloud Run + API Gateway + GCS 持久化)
├── deploy.sh                # 极速 Cloud Run 更新部署脚本 (复用已有 Gateway，数十秒即可生效)
├── run_local.sh             # 本地极速启动脚本
├── requirements.txt         # Python 依赖清单
└── README.md
```

---

## 🚀 快速上手使用

### 1. 本地启动测试
```bash
./run_local.sh
```
浏览器打开：`http://localhost:8080` 即可开始录音测试！

---

### 2. 部署到云端并获得公网免密 HTTPS（供手机 7×24h 随时使用）

- **首次完整部署（配置 Cloud Run、持久化存储桶与 API Gateway 网关）**：
  ```bash
  ./setup_gateway.sh
  ```
- **日常迭代更新部署（数十秒即可完成，自动同步持久化）**：
  ```bash
  ./deploy.sh
  ```

部署完成后，终端会自动输出专属于你的永久 HTTPS 地址：
`https://voice-spark-gateway-5lquvkm5.ew.gateway.dev`

#### ⚠️ Cloud Run 核心生产配置（部署脚本已全内置）：
1. **Google Cloud Storage (GCS) 云端双向持久化**：
   * 环境变量传入 `GCS_BUCKET=voice-spark-data-cjlinn-471522`、`STORAGE_SYNC_ENABLED=true`。
   * 容器启动时通过 `python -m backend.prestart` 从 GCS 恢复数据库、录音文件与 VAPID 密钥；运行中每次新增灵感或状态变更均原子同步，关机时平滑执行最终落盘备份。
2. **`--no-cpu-throttling`（CPU 始终分配）**：保证接收到录音返回 202 后，后台多模态提炼与转写能全速执行不被休眠。
3. **`--min-instances 1`（保持至少 1 个常驻实例）**：保持常驻实例，彻底消除冷启动。
4. **`--max-instances 1`（限制单实例）**：保证所有语音写入同一个活跃实例，避免多实例数据割裂。

---

## 📱 手机端配置与使用

1. **安装为 iPhone App**：
   * 在 iPhone Safari 打开你的专属域名。
   * 点击底部「分享」图标 ➔ 选择 **「添加到主屏幕」**。
2. **开启锁屏推送**：
   * 打开 VoiceSpark 图标，点击右上角铃铛 **`🔔`**，允许通知权限。
3. **配置 iPhone 操作按钮 (Action Button) 一键录音**：
   * 参考 [`shortcuts/ios_shortcut_guide.md`](shortcuts/ios_shortcut_guide.md) 中的说明，在快捷指令中添加 3 个积木块。
   * 绑定到侧边操作按钮或锁屏小组件，随时随地一按即录！
4. **联动 OurTodo PWA**：
   * 点击右上角齿轮 **`⚙️`**，输入你的 OurTodo 域名（如 `https://todo-gateway-xxxx.ew.gateway.dev`）。
   * 之后在任一灵感胶囊中点击 **「送往 OurTodo」**，即可将待办无缝加入协同清单！
