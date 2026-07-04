# GPT-SoVITS 详细配置指南

本文档详细说明如何配置 GPT-SoVITS 以使用 Sakura 桌宠的角色语音权重。

---

## 前置准备

### 硬件要求
- **NVIDIA GPU**（必需）：语音合成需要 CUDA 加速
- **显存要求**：至少 4GB（推荐 6GB 以上）
- **系统**：Windows 10/11

### 软件要求
- Windows 10/11
- NVIDIA 驱动（支持 CUDA 11.8 或更高）
- Python 3.10 或 3.11（推荐 3.11）

---

## 一、安装 GPT-SoVITS

### 方法 1：使用整合包（推荐）

1. 下载 GPT-SoVITS v2 Pro Plus 整合包：
   - 官方 Release：https://github.com/RVC-Boss/GPT-SoVITS/releases
   - 选择带有 `windows` 和 `整合包` 标签的版本

2. 解压到纯英文路径（**路径不能包含中文或空格**）：
   ```
   例如：D:\GPT-SoVITS
   不要用：D:\我的文件\GPT-SoVITS（包含中文）
   不要用：D:\Program Files\GPT-SoVITS（包含空格）
   ```

3. 验证安装：
   - 解压后目录应包含：
     ```
     D:\GPT-SoVITS\
     ├── runtime\              # Python 环境
     │   └── python.exe
     ├── GPT_SoVITS\          # 核心代码
     ├── tools\
     ├── api_v2.py            # API 服务入口
     └── go-webui.bat         # Web UI 启动脚本
     ```

### 方法 2：从源码安装

```bash
git clone https://github.com/RVC-Boss/GPT-SoVITS.git
cd GPT-SoVITS
pip install -r requirements.txt
```

---

## 二、启动 GPT-SoVITS API 服务

### 使用整合包启动

1. 进入 GPT-SoVITS 安装目录：
   ```cmd
   cd D:\GPT-SoVITS
   ```

2. 启动 API 服务（**默认端口 9880**）：
   ```cmd
   runtime\python.exe api_v2.py -p 9880
   ```

   或者指定自定义端口：
   ```cmd
   runtime\python.exe api_v2.py -p 9874
   ```

3. 看到以下输出表示启动成功：
   ```
   INFO:     Started server process
   INFO:     Uvicorn running on http://127.0.0.1:9880
   ```

### 使用源码启动

```bash
python api_v2.py -p 9880
```

---

## 三、配置 Sakura 角色语音权重

### 步骤 1：理解路径结构

Sakura 角色语音权重已内置在仓库中：

```
sakura-desktop-pet-characters/
├── characters/
│   ├── chun/
│   │   └── voice/
│   │       ├── models/
│   │       │   ├── chun-e15.ckpt       # GPT 权重
│   │       │   └── chun_e6_s96.pth     # SoVITS 权重
│   │       ├── chun_ref.wav            # 参考音频
│   │       └── tone_refs.txt           # 音色配置
│   │
│   └── atri/
│       └── voice/
│           ├── models/
│           │   ├── yatuoli-e15.ckpt    # GPT 权重
│           │   └── yatuoli_e8_s232.pth # SoVITS 权重
│           ├── refs/tone_refs/
│           │   └── ATR_b101_021.wav    # 参考音频
│           └── tone_refs.txt           # 音色配置
```

### 步骤 2：配置 api.yaml

1. 复制配置示例：
   ```bash
   cd D:\sakura-desktop-pet-characters
   copy data\config\api.yaml.example data\config\api.yaml
   ```

2. 编辑 `data\config\api.yaml`，填入实际配置：

   ```yaml
   llm:
     # LLM API 配置（使用 OpenAI / Claude / 其他兼容接口）
     base_url: https://api.openai.com/v1
     api_key: sk-xxxxxxxxxxxxxxxxxxxxxxxx  # 替换为你的 API key
     model: gpt-4
     timeout_seconds: 60

   tts:
     provider: gpt-sovits
     enabled: true
     
     gpt_sovits:
       # GPT-SoVITS API 地址（必须与启动的端口一致）
       api_url: http://127.0.0.1:9880/tts
       
       # GPT-SoVITS 安装路径（修改为你的实际路径）
       work_dir: D:/GPT-SoVITS
       python_path: D:/GPT-SoVITS/runtime/python.exe
       
       # 语言设置
       ref_lang: zh
       text_lang: zh
       text_split_method: cut0
       timeout_seconds: 120
   ```

   **关键参数说明**：
   - `api_url`：必须与 `api_v2.py` 启动的端口一致（默认 9880）
   - `work_dir`：GPT-SoVITS 的**绝对路径**（不能是相对路径）
   - `python_path`：GPT-SoVITS 环境中的 python.exe 路径
   - `ref_lang` / `text_lang`：
     - 椿（chun）：两者都填 `zh`（中文音色）
     - 亚托莉（atri）：`ref_lang: ja`，`text_lang: ja`（日文音色）

### 步骤 3：角色语音权重路径说明

**重要**：角色的 `character.json` 已配置好相对路径，无需手动修改。

- **椿（chun）**：
  ```json
  "voice": {
    "gpt_model": "voice/models/chun-e15.ckpt",
    "sovits_model": "voice/models/chun_e6_s96.pth",
    "tone_refs": "tone_refs.txt",
    "ref_lang": "zh",
    "text_lang": "zh"
  }
  ```

- **亚托莉（atri）**：
  ```json
  "voice": {
    "gpt_model": "voice/models/yatuoli-e15.ckpt",
    "sovits_model": "voice/models/yatuoli_e8_s232.pth",
    "tone_refs": "voice/tone_refs.txt",
    "ref_lang": "ja",
    "text_lang": "ja"
  }
  ```

这些路径是**相对于角色目录的相对路径**，例如：
- `characters/chun/voice/models/chun-e15.ckpt`
- `characters/atri/voice/models/yatuoli-e15.ckpt`

Sakura 启动时会自动解析为绝对路径并传递给 GPT-SoVITS API。

---

## 四、测试语音合成

### 测试 GPT-SoVITS API 是否正常

在浏览器访问：
```
http://127.0.0.1:9880/docs
```

应该能看到 FastAPI 自动生成的 API 文档页面。

### 使用 Sakura 测试语音

1. 确保 GPT-SoVITS API 服务已启动（端口 9880）

2. 启动 Sakura 椿角色：
   ```cmd
   cd D:\sakura-desktop-pet-characters
   start_chun.bat
   ```

3. 在桌宠对话框输入消息，观察：
   - 文字回复是否正常
   - 是否播放语音
   - 控制台是否有 TTS 相关错误

### 常见测试场景

| 角色 | 输入 | 预期语音 | 预期文字 |
|-----|------|---------|---------|
| 椿（chun） | 你好 | 中文语音 | 中文回复 |
| 亚托莉（atri） | こんにちは | 日文语音 | 中文字幕（显示） + 日文语音（朗读） |

---

## 五、故障排查

### 问题 1：启动 API 服务时报错 `ModuleNotFoundError`

**原因**：Python 环境缺少依赖。

**解决**：
```cmd
cd D:\GPT-SoVITS
runtime\python.exe -m pip install -r requirements.txt
```

### 问题 2：Sakura 启动时提示 `TTS service unavailable`

**排查步骤**：

1. 检查 GPT-SoVITS API 是否启动：
   ```cmd
   curl http://127.0.0.1:9880/docs
   ```
   应该返回 HTML 内容。

2. 检查 `api.yaml` 配置：
   - `api_url` 端口是否与启动命令一致
   - `work_dir` 路径是否正确（注意反斜杠 `\` 或正斜杠 `/`）

3. 查看 Sakura 控制台日志，搜索 `TTS` 关键词查看具体错误。

### 问题 3：语音播放卡顿或无声

**可能原因**：
- GPU 显存不足
- 权重文件损坏
- 参考音频格式不兼容

**解决**：
1. 检查 GPU 显存占用：
   ```cmd
   nvidia-smi
   ```

2. 验证权重文件完整性：
   ```cmd
   cd D:\sakura-desktop-pet-characters
   python -c "from pathlib import Path; files = ['characters/chun/voice/models/chun-e15.ckpt', 'characters/chun/voice/models/chun_e6_s96.pth', 'characters/atri/voice/models/yatuoli-e15.ckpt', 'characters/atri/voice/models/yatuoli_e8_s232.pth']; [print(f'{\"✅\" if Path(f).exists() else \"❌\"} {f}') for f in files]"
   ```

3. 检查参考音频：
   ```cmd
   # 椿
   ffprobe characters\chun\chun_ref.wav
   
   # 亚托莉
   ffprobe characters\atri\voice\refs\tone_refs\ATR_b101_021.wav
   ```

### 问题 4：亚托莉语音是中文而非日文

**原因**：`api.yaml` 中 `ref_lang` / `text_lang` 配置错误。

**解决**：
检查 `data/config/api.yaml`：
```yaml
tts:
  gpt_sovits:
    ref_lang: ja   # 必须是 ja
    text_lang: ja  # 必须是 ja
```

注意：亚托莉的 `character.json` 使用 `language_policy` 确保回复格式正确（日文语音 + 中文字幕）。

### 问题 5：端口冲突

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
   
3. 同步修改 `api.yaml` 中的 `api_url`：
   ```yaml
   api_url: http://127.0.0.1:9874/tts
   ```

---

## 六、进阶配置

### 自定义音色

1. 准备参考音频（WAV 格式，推荐 16kHz/22.05kHz）

2. 训练 GPT-SoVITS 权重（参考官方文档）

3. 修改角色的 `character.json`：
   ```json
   "voice": {
     "gpt_model": "voice/models/your-model.ckpt",
     "sovits_model": "voice/models/your-model.pth",
     "tone_refs": "your_refs.txt",
     "ref_lang": "zh",
     "text_lang": "zh"
   }
   ```

### 多角色同时启动

每个角色使用独立的 `data/pets/<character_id>/` 目录存储对话历史和记忆，可以同时启动多个角色而不会相互干扰。

启动方式：
```cmd
# 终端 1：启动椿
start_chun.bat

# 终端 2：启动亚托莉
start_atri.bat
```

---

## 七、参考资源

- GPT-SoVITS 官方仓库：https://github.com/RVC-Boss/GPT-SoVITS
- GPT-SoVITS 文档：https://github.com/RVC-Boss/GPT-SoVITS/wiki
- Sakura 原始仓库：https://github.com/Rvosy/sakura
- 本仓库 Issues：https://github.com/lyqi712/sakura-desktop-pet-characters/issues

---

## 八、常见问题汇总

| 问题 | 原因 | 解决方法 |
|-----|------|---------|
| `runtime\python.exe not found` | 未安装 Python 环境 | 下载 Python 3.11 embedded 或使用 virtualenv |
| `TTS service unavailable` | GPT-SoVITS API 未启动 | 运行 `api_v2.py` |
| `Address already in use` | 端口被占用 | 更换端口或杀死占用进程 |
| 语音卡顿 | GPU 显存不足 | 关闭其他 GPU 程序 |
| 无法加载权重 | 路径错误或文件损坏 | 检查路径和文件完整性 |
| 亚托莉说中文语音 | `ref_lang` 配置错误 | 改为 `ja` |

---

**最后更新**：2026-07-04  
**适用版本**：GPT-SoVITS v2 Pro Plus
