# 达妮娅（Dania）

**配置模板**，不包含 PMX 模型、纹理与语音权重（版权归广州库洛科技有限公司，授权文件明确禁止再配布）。

## 资源状态

- ❌ MMD (PMX) 模型与纹理（需用户自备）
- ❌ 语音权重与参考音频（需用户自备或自行训练）
- ❌ 头像图片（需用户自备）
- ✅ 角色卡片（`card.md`）
- ✅ 配置模板（`character.json`）

## 如何使用

### 1. 准备 PMX 模型

从《鸣潮》官方渠道获取授权模型后，放入：

```
characters/dania/model_variants/
├── 红色一形态/.../*.pmx
└── 蓝色二形态/.../*.pmx
```

在 `character.json` 中启用 renderer：

- 将 `_renderer_disabled` 字段改名为 `renderer`
- 填入 `model` 和 `model_variants.red.model` / `model_variants.blue.model` 实际路径

### 2. 准备语音权重（可选）

使用 GPT-SoVITS 训练中文语音权重，或获取授权权重后：

1. 准备参考音频（`.wav`）和 `tone_refs.txt`
2. 将 GPT 权重与 SoVITS 权重放入可访问路径
3. 在 `character.json` 中启用 voice：
   - 将 `_voice_disabled` 字段改名为 `voice`
   - 填入 `gpt_model`、`sovits_model`、`tone_refs` 实际路径

### 3. 准备头像（可选）

放置 `portrait_default.png` 到当前目录，并在 `portrait` 段增加：

```json
"default": "portrait_default.png"
```

## 版权说明

本模板仅包含配置文本，不包含《鸣潮》的游戏资源。模型原始授权文件明确禁止再配布（Redistribution is not allowed），最终版权归广州库洛科技有限公司所有。请在获得适当授权后再使用相关资源。
