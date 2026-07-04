# 亚托莉（ATRI）

**配置模板**，不包含 Live2D 模型与语音权重（提取自《ATRI -My Dear Moments-》游戏客户端，存在版权/再配布风险）。

## 资源状态

- ❌ Live2D 模型（需用户自备）
- ❌ 语音权重与参考音频（需用户自备或自行训练）
- ❌ 头像图片（需用户自备）
- ✅ 角色卡片（`card.md`）
- ✅ 配置模板（`character.json`）

## 如何使用

### 1. 准备 Live2D 模型

从游戏客户端提取或自行获取授权后，放入：

```
characters/atri/live2d/
└── atri_8.model3.json
```

在 `character.json` 中启用 renderer：

- 将 `_renderer_disabled` 字段改名为 `renderer`
- 确认 `model` 字段指向 `atri_8.model3.json`

### 2. 准备语音权重（可选）

使用 GPT-SoVITS 训练日文语音权重，或获取授权权重后：

1. 准备参考音频（`.wav`）和 `tone_refs.txt`
2. 将 GPT 权重与 SoVITS 权重放入可访问路径
3. 在 `character.json` 中启用 voice：
   - 将 `_voice_disabled` 字段改名为 `voice`
   - 填入 `gpt_model`、`sovits_model`、`tone_refs` 实际路径

### 3. 准备头像（可选）

放置 `portrait_default.jpg` 到当前目录，并在 `portrait` 段增加：

```json
"default": "portrait_default.jpg"
```

## 版权说明

本模板仅包含配置文本，不包含《ATRI -My Dear Moments-》的游戏资源。请在获得适当授权后再使用相关资源。
