# WorkBuddy Skills

我自己的 WorkBuddy 技能仓库。每做完一件值得复用的事，就把流程固化成技能放进来。

## 技能列表

| 技能 | 说明 | 状态 |
|---|---|---|
| [comfyui-batch-video](comfyui-batch-video/) | 用本地 ComfyUI（MiniMax-H3 + Pika LoRA）批量生产 9:16 竖屏短视频，并加中文字幕 | 已实测，产出 70+ 条成品 |

## 安装方式

把技能目录复制到 WorkBuddy 的用户技能目录：

```bash
# Windows
xcopy /E /I comfyui-batch-video "%USERPROFILE%\.workbuddy-ai\skills\comfyui-batch-video"

# macOS / Linux
cp -r comfyui-batch-video ~/.workbuddy-ai/skills/
```

重启会话后，在对话里说需求即可自动匹配，或显式调用 `/comfyui-batch-video`。

## 技能结构约定

每个技能遵循同一套结构：

```
<skill-name>/
├── SKILL.md          # 必需：YAML frontmatter（name/description/agent_created）+ 指令正文
├── scripts/          # 可选：可执行脚本，确定性操作用代码而非重写
├── references/       # 可选：按需加载的详细文档
└── assets/           # 可选：模板、样例等产出用文件
```

写技能时只记录**非显而易见**的东西——踩过的坑、验证过的参数、失败的方案。
常识性内容不写，省上下文。

## 注意事项

- 技能里不含任何密钥或凭据
- 部分脚本含本机路径（`N:\ComfyUI_portable_TE_v260619`），换机器需改 `--config` 或让脚本自动探测
- 生成类参数是实测跑通的，改动前先单条验证
