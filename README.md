# Sakura Desktop Pet - Open Source Release

基于 [Rvosy/sakura](https://github.com/Rvosy/sakura) 的 AI 桌宠整理版，包含主程序源码与三个角色（2 个完整 + 1 个模板）。

## 特性

- 🎭 **多角色支持**：椿（完整）、亚托莉（完整）、达妮娅（模板）
- 🎨 **Live2D / MMD 渲染**：支持 Live2D Cubism SDK 和 Three.js MMD 渲染
- 🎤 **GPT-SoVITS 语音**：集成 GPT-SoVITS v2 Pro Plus，支持多音色、分段语音、嘴型同步
- 💬 **LLM 对话**：支持 OpenAI / Claude / 其他兼容 API
- 🧠 **长期记忆**：基于 Mem0 的持久化记忆系统
- 🔧 **插件系统**：可扩展插件架构

---

## 快速开始

### 环境要求

- **操作系统**：Windows 10/11
- **Python**：3.10+ (推荐 3.11)
- **GPU**：NVIDIA GPU（语音合成需要 CUDA）
- **显存**：至少 4GB（推荐 6GB 以上）

### 安装步骤

#### 1. 克隆仓库

```bash
git clone https://github.com/lyqi712/sakura-desktop-pet-characters.git
cd sakura-desktop-pet-characters
```

#### 2. 安装 Python 依赖

⚠️ **重要**：项目路径必须是纯英文，不能包含中文或空格（PySide6 限制）。

**方案 A：使用 virtualenv（推荐）**

```bash
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

**方案 B：使用 embedded Python**

1. 下载 [Python 3.11 embedded](https://www.python.org/downloads/windows/)
2. 解压到 `runtime/` 目录
3. 安装依赖：
   ```cmd
   runtime\python.exe -m pip install -r requirements.txt
   ```

#### 3. 安装 GPT-SoVITS

**推荐方式：使用整合包**

1. 下载 GPT-SoVITS v2 Pro Plus 整合包：
   - 官方 Release：https://github.com/RVC-Boss/GPT-SoVITS/releases
   - 选择带有 `windows` 和 `整合包` 标签的版本

2. 解压到纯英文路径（例如 `D:\GPT-SoVITS`）

3. 启动 API 服务（**必须先启动才能使用语音**）：
   ```cmd
   cd D:\GPT-SoVITS
   runtime\python.exe api_v2.py -p 9880
   ```

   看到以下输出表示成功：
   ```
   INFO:     Uvicorn running on http://127.0.0.1:9880
   ```

📖 **详细配置说明**：参见 [GPT-SoVITS 详细配置指南](docs/GPT-SoVITS-Setup.md)

#### 4. 配置 API 密钥

1. 复制配置示例：
   ```cmd
   copy data\config\api.yaml.example data\config\api.yaml
   ```

2. 编辑 `data/config/api.yaml`，填入你的配置：

   ```yaml
   llm:
     base_url: https://api.openai.com/v1
     api_key: sk-xxxxxxxxxxxxxxxxxxxxxxxx  # 替换为你的 API key
     model: gpt-4
     timeout_seconds: 60

   tts:
     provider: gpt-sovits
     enabled: true
     
     gpt_sovits:
       api_url: http://127.0.0.1:9880/tts
       work_dir: D:/GPT-SoVITS          # 修改为你的 GPT-SoVITS 路径
       python_path: D:/GPT-SoVITS/runtime/python.exe
       ref_lang: zh
       text_lang: zh
       timeout_seconds: 120
   ```

   **关键参数**：
   - `api_key`：你的 LLM API 密钥（OpenAI / Claude 等）
   - `work_dir`：GPT-SoVITS 的**绝对路径**
   - `api_url`：必须与 `api_v2.py` 启动的端口一致

#### 5. 启动桌宠

**启动椿（中文语音）：**
```cmd
start_chun.bat
```

**启动亚托莉（日文语音 + 中文字幕）：**
```cmd
start_atri.bat
```

**启动达妮娅（需要自行准备模型和权重）：**
```cmd
start.bat
```

---

## 角色说明

### 椿（Chun）✅ 完整可用

- **包含资源**：Live2D 模型、语音权重（278 MB）、参考音频、头像、角色卡片
- **语言**：中文语音 + 中文文字
- **特点**：危险又迷人的共鸣者，黑海岸执花
- **启动方式**：`start_chun.bat`
- **详细说明**：[characters/chun/README.md](characters/chun/README.md)

**语音权重**：
- GPT 模型：`characters/chun/voice/models/chun-e15.ckpt`
- SoVITS 模型：`characters/chun/voice/models/chun_e6_s96.pth`
- 参考音频：`characters/chun/chun_ref.wav`

### 亚托莉（ATRI）✅ 完整可用

- **包含资源**：Live2D 模型、语音权重（278 MB）、参考音频、头像、角色卡片
- **语言**：日文语音 + 中文字幕（显示中文，朗读日文）
- **特点**：高性能仿生少女，情感丰富、认真努力
- **启动方式**：`start_atri.bat`
- **详细说明**：[characters/atri/README.md](characters/atri/README.md)

**语音权重**：
- GPT 模型：`characters/atri/voice/models/yatuoli-e15.ckpt`
- SoVITS 模型：`characters/atri/voice/models/yatuoli_e8_s232.pth`
- 参考音频：`characters/atri/voice/refs/tone_refs/ATR_b101_021.wav`

**配置说明**：
亚托莉使用双语模式，配置文件中需要设置：
```yaml
tts:
  gpt_sovits:
    ref_lang: ja   # 参考音频语言：日文
    text_lang: ja  # 合成语音语言：日文
```

角色的 `character.json` 通过 `language_policy` 确保回复格式：
```json
"language_policy": {
  "mode": "bilingual_segments",
  "text_lang": "zh",    // 界面显示中文
  "voice_lang": "ja",   // TTS 朗读日文
  "disallowed_langs": ["en"]
}
```

### 达妮娅（Dania）⚠️ 仅配置模板

- **包含资源**：仅配置文件（22 KB）
- **不包含**：PMX 模型、语音权重（授权文件明确禁止再配布）
- **状态**：需用户自行获取授权资源后启用
- **启动方式**：`start.bat`（需先准备资源）
- **详细说明**：[characters/dania/README.md](characters/dania/README.md)

---

## 使用教程

### 切换角色

每个角色有独立的启动脚本和数据目录：

```
data/pets/
├── chun/      # 椿的对话历史和记忆
├── atri/      # 亚托莉的对话历史和记忆
└── dania/     # 达妮娅的对话历史和记忆
```

**多角色同时启动**：可以同时打开多个终端运行不同角色，它们不会互相干扰。

### 对话交互

1. 启动桌宠后，Live2D 角色会显示在桌面右下角
2. 点击角色图标打开对话窗口
3. 在输入框输入消息，按回车发送
4. 角色会用文字回复，并播放语音（如果启用了 TTS）

### 语音开关

- 在对话窗口中可以切换语音开关
- 椿：朗读中文
- 亚托莉：朗读日文（界面显示中文翻译）

### 自定义配置

#### 修改角色行为

编辑 `characters/<角色ID>/card.md` 修改角色设定。

#### 调整 Live2D 显示

编辑 `characters/<角色ID>/character.json` 中的 `renderer` 部分：

```json
"renderer": {
  "type": "live2d",
  "model_scale": 0.7,      // 模型缩放
  "half_scale": 1.48,      // 半身模式缩放
  "resolution_scale": 2.5, // 分辨率倍数
  "half_offset_y": 0.0     // 垂直偏移
}
```

#### 更换语音权重

如果你训练了自己的 GPT-SoVITS 模型：

1. 将权重文件放入 `characters/<角色ID>/voice/models/`
2. 修改 `character.json`：
   ```json
   "voice": {
     "gpt_model": "voice/models/your-model.ckpt",
     "sovits_model": "voice/models/your-model.pth",
     "tone_refs": "tone_refs.txt",
     "ref_lang": "zh",
     "text_lang": "zh"
   }
   ```

---

## 故障排查

### 1. 启动时报错 `runtime\python.exe not found`

**原因**：未安装 Python 环境或路径错误。

**解决**：
- 方案 A：使用 virtualenv，创建 `venv` 目录
- 方案 B：下载 Python 3.11 embedded 并放入 `runtime/` 目录

### 2. 语音无法播放 / TTS service unavailable

**检查清单**：

1. **GPT-SoVITS API 是否启动**：
   ```cmd
   curl http://127.0.0.1:9880/docs
   ```
   应该返回 HTML 页面。

2. **api.yaml 配置是否正确**：
   - `api_url` 端口与启动命令一致
   - `work_dir` 是 GPT-SoVITS 的绝对路径（不能是相对路径）

3. **语音权重文件是否存在**：
   ```cmd
   python -c "from pathlib import Path; files = ['characters/chun/voice/models/chun-e15.ckpt', 'characters/chun/voice/models/chun_e6_s96.pth', 'characters/atri/voice/models/yatuoli-e15.ckpt', 'characters/atri/voice/models/yatuoli_e8_s232.pth']; [print(f'{\"✅\" if Path(f).exists() else \"❌\"} {f}') for f in files]"
   ```
   应该全部显示 ✅。

4. **查看详细日志**：启动桌宠时，控制台会输出 TTS 相关日志，搜索 `TTS` 或 `ERROR` 关键词。

📖 **详细排查步骤**：参见 [GPT-SoVITS 详细配置指南 - 故障排查](docs/GPT-SoVITS-Setup.md#五故障排查)

### 3. 路径包含中文导致无法启动

**报错**：`Project path contains non-English chars`

**原因**：PySide6 在非 ASCII 路径下会崩溃。

**解决**：
1. 将项目移动到纯英文路径，例如：
   - ✅ `D:\sakura`
   - ✅ `C:\Users\Administrator\sakura`
   - ❌ `D:\我的文件\sakura`（包含中文）
   - ❌ `D:\Program Files\sakura`（包含空格）

2. 重新运行启动脚本。

### 4. GPU 显存不足

**症状**：语音卡顿、崩溃、或提示 `CUDA out of memory`。

**解决**：
1. 关闭其他占用 GPU 的程序（游戏、视频编辑软件等）
2. 检查显存占用：
   ```cmd
   nvidia-smi
   ```
3. 如果显存小于 4GB，考虑：
   - 降低 Live2D 分辨率（修改 `resolution_scale`）
   - 关闭语音合成（`api.yaml` 中设置 `enabled: false`）

### 5. 端口冲突

**报错**：`Address already in use: 9880`

**解决**：
1. 查找占用进程：
   ```cmd
   netstat -ano | findstr 9880
   ```

2. 杀死进程或使用其他端口：
   ```cmd
   runtime\python.exe api_v2.py -p 9874
   ```

3. 同步修改 `api.yaml`：
   ```yaml
   api_url: http://127.0.0.1:9874/tts
   ```

---

## 项目结构

```
sakura-desktop-pet-characters/
├── app/                    # 核心应用代码
│   ├── config/            # 配置加载（角色、API）
│   ├── core/              # 核心逻辑（对话、TTS、记忆）
│   ├── gui/               # PyQt6 GUI
│   └── utils/             # 工具函数
├── plugins/               # 插件目录
├── characters/            # 角色目录
│   ├── chun/             # 椿（完整）
│   │   ├── voice/
│   │   │   ├── models/
│   │   │   │   ├── chun-e15.ckpt       # GPT 权重 (278 MB)
│   │   │   │   └── chun_e6_s96.pth     # SoVITS 权重
│   │   │   ├── chun_ref.wav            # 参考音频
│   │   │   └── tone_refs.txt
│   │   ├── live2d/
│   │   ├── character.json
│   │   └── card.md
│   ├── atri/             # 亚托莉（完整）
│   │   ├── voice/
│   │   │   ├── models/
│   │   │   │   ├── yatuoli-e15.ckpt    # GPT 权重 (278 MB)
│   │   │   │   └── yatuoli_e8_s232.pth # SoVITS 权重
│   │   │   ├── refs/tone_refs/
│   │   │   │   └── ATR_b101_021.wav    # 参考音频
│   │   │   └── tone_refs.txt
│   │   ├── live2d/
│   │   ├── character.json
│   │   └── card.md
│   └── dania/            # 达妮娅（模板）
│       ├── character.json
│       └── README.md
├── tests/                 # 单元测试
├── scripts/               # 工具脚本
├── tools/                 # 外部工具集成
├── third_party/           # 第三方库（mem0）
├── data/                  # 运行时数据
│   ├── config/
│   │   ├── api.yaml.example    # 配置示例
│   │   └── api.yaml            # 用户配置（不提交）
│   └── pets/
│       ├── chun/              # 椿的数据
│       ├── atri/              # 亚托莉的数据
│       └── dania/             # 达妮娅的数据
├── docs/                  # 文档
│   └── GPT-SoVITS-Setup.md    # GPT-SoVITS 详细配置指南
├── main.py               # 主入口
├── start_chun.bat        # 启动椿
├── start_atri.bat        # 启动亚托莉
├── start.bat             # 启动达妮娅
├── requirements.txt      # Python 依赖
└── README.md             # 本文件
```

---

## 开发

### 运行测试

```bash
pytest tests/unit/ -v
```

### 打包角色

使用内置脚本导出 `.char` 角色包（开发中）：

```bash
python scripts/package_character.py --character chun --output ./chun.char
```

### 导入角色

将 `.char` 包放入 `characters/` 目录并导入（开发中）：

```bash
python scripts/import_character.py --char ./custom.char
```

---

## 关于整合包

本仓库**不提供整合包**（包含 Python 环境、GPT-SoVITS、所有依赖的一键启动包），原因：

1. **体积过大**：完整整合包超过 5 GB（Python runtime + GPT-SoVITS + 依赖库）
2. **版本灵活性**：用户可以自行选择 GPT-SoVITS 版本和 Python 环境
3. **许可证兼容性**：避免打包第三方库可能的许可证冲突

**推荐方式**：

- Python 环境：使用 virtualenv 或 Python embedded（轻量，~50 MB）
- GPT-SoVITS：使用官方整合包（已包含 runtime，~4 GB）
- 本仓库：仅克隆源码 + 角色资源（~650 MB）

---

## 限制与注意事项

- **版权**：
  - 椿：Live2D 模型与语音资源来源待确认，如您是原作者或版权持有者请联系
  - 亚托莉：资源提取自《ATRI -My Dear Moments-》游戏客户端，仅供学习交流
  - 达妮娅：不包含二进制资源（授权限制），需自行获取
- **GPU**：语音合成需要 NVIDIA GPU（CUDA），CPU 模式不支持
- **路径**：项目路径必须是纯英文，不能包含中文或空格（PySide6 限制）
- **许可证兼容性**：避免将 GPL-3.0 项目（如 MoeChat）混入本仓库

---

## 许可证

本项目基于 [Rvosy/sakura](https://github.com/Rvosy/sakura) 源码整理，遵循 MIT 许可证。

第三方库许可证：

- `third_party/mem0`: Apache License 2.0
- `GPT-SoVITS`: MIT License（独立项目，不随本仓库打包）
- `Live2D Cubism SDK`: [Live2D 许可证](https://www.live2d.com/sdk/)

角色资源许可证见各角色 `README.md`。

---

## 贡献

欢迎提交 Issue 和 Pull Request。

**提交前请确保**：
- 测试通过：`pytest tests/unit/ -v`
- 代码符合项目风格
- 提交信息清晰

---

## 联系

- 原作者：[Rvosy](https://github.com/Rvosy)
- 本仓库维护者：[lyqi712](https://github.com/lyqi712)
- Issues：https://github.com/lyqi712/sakura-desktop-pet-characters/issues

---

## 致谢

- [Rvosy/sakura](https://github.com/Rvosy/sakura) - 原始项目
- [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) - 语音合成
- [Mem0](https://github.com/mem0ai/mem0) - 记忆系统
- [Live2D Cubism SDK](https://www.live2d.com/sdk/) - Live2D 渲染
- [Three.js](https://threejs.org/) - MMD 渲染

---

**最后更新**：2026-07-04  
**版本**：v1.0
