# Sakura Desktop Pet - Open Source Release

基于 [Rvosy/sakura](https://github.com/Rvosy/sakura) 的 AI 桌宠整理版，包含主程序源码与三个角色（1 个完整 + 2 个模板）。

## 特性

- 🎭 **多角色支持**：椿（完整）、亚托莉（模板）、达妮娅（模板）
- 🎨 **Live2D / MMD 渲染**：支持 Live2D Cubism SDK 和 Three.js MMD 渲染
- 🎤 **GPT-SoVITS 语音**：集成 GPT-SoVITS v2 Pro Plus，支持多音色、分段语音、嘴型同步
- 💬 **LLM 对话**：支持 OpenAI / Claude / 其他兼容 API
- 🧠 **长期记忆**：基于 Mem0 的持久化记忆系统
- 🔧 **插件系统**：可扩展插件架构

## 快速开始

### 环境要求

- Windows 10/11
- Python 3.10+ (推荐 3.11)
- NVIDIA GPU（语音合成需要 CUDA）

### 安装步骤

1. **克隆仓库**

   ```bash
   git clone https://github.com/lyqi712/sakura-desktop-pet-characters.git
   cd sakura-desktop-pet-characters
   ```

2. **安装依赖**

   ```bash
   pip install -r requirements.txt
   pip install -r requirements-dev.txt  # 开发/测试依赖（可选）
   ```

3. **安装 GPT-SoVITS**

   从 [GPT-SoVITS v2 Pro Plus](https://github.com/RVC-Boss/GPT-SoVITS) 下载并安装，或使用整合包：

   ```bash
   # 启动 GPT-SoVITS API 服务（默认端口 9880）
   python api_v2.py
   ```

4. **配置 API 密钥**

   编辑 `data/config/api.yaml`：

   ```yaml
   openai:
     api_key: "your-api-key"
     base_url: "https://api.openai.com/v1"
     model: "gpt-4"
   
   gpt_sovits:
     base_url: "http://127.0.0.1:9880"
   ```

5. **启动桌宠**

   ```bash
   python main.py
   ```

   或使用批处理：

   ```bash
   start.bat
   ```

## 角色说明

### 椿（Chun）✅ 完整可用

- 包含 Live2D 模型、语音参考音频、头像
- 可直接使用，无需额外准备资源
- 详见 [characters/chun/README.md](characters/chun/README.md)

### 亚托莉（ATRI）⚠️ 仅配置模板

- 不包含 Live2D 模型与语音权重（游戏资源提取，存在版权风险）
- 需用户自行准备资源后启用
- 详见 [characters/atri/README.md](characters/atri/README.md)

### 达妮娅（Dania）⚠️ 仅配置模板

- 不包含 PMX 模型与语音权重（授权文件明确禁止再配布）
- 需用户自行获取授权资源后启用
- 详见 [characters/dania/README.md](characters/dania/README.md)

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
│   ├── atri/             # 亚托莉（模板）
│   └── dania/            # 达妮娅（模板）
├── tests/                 # 单元测试
├── scripts/               # 工具脚本
├── tools/                 # 外部工具集成
├── third_party/           # 第三方库（mem0）
├── main.py               # 主入口
├── requirements.txt      # Python 依赖
└── README.md             # 本文件
```

## 测试

运行单元测试：

```bash
pytest tests/unit/ -v
```

## 限制与注意事项

- **版权**：亚托莉、达妮娅模板不包含二进制资源，请在获得授权后使用
- **GPU**：语音合成需要 NVIDIA GPU（CUDA），CPU 模式不支持
- **许可证兼容性**：避免将 GPL-3.0 项目（如 MoeChat）混入本仓库

## 开发

### 打包角色

使用内置脚本导出 `.char` 角色包：

```bash
python scripts/package_character.py --character chun --output ./chun.char
```

### 导入角色

将 `.char` 包放入 `characters/` 目录并导入：

```bash
python scripts/import_character.py --char ./custom.char
```

## 许可证

本项目基于 [Rvosy/sakura](https://github.com/Rvosy/sakura) 源码整理，遵循 MIT 许可证。

第三方库许可证：

- `third_party/mem0`: Apache License 2.0
- `GPT-SoVITS`: MIT License（独立项目，不随本仓库打包）

角色资源许可证见各角色 `README.md`。

## 贡献

欢迎提交 Issue 和 Pull Request。

## 联系

- 原作者：[Rvosy](https://github.com/Rvosy)
- 本仓库维护者：[lyqi712](https://github.com/lyqi712)

## 致谢

- [Rvosy/sakura](https://github.com/Rvosy/sakura) - 原始项目
- [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) - 语音合成
- [Mem0](https://github.com/mem0ai/mem0) - 记忆系统
- [Live2D Cubism SDK](https://www.live2d.com/sdk/) - Live2D 渲染
- [Three.js](https://threejs.org/) - MMD 渲染
