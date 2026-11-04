---
name: comfyui-batch-video
description: 用本地 ComfyUI 的 MiniMax-H3 + Pika 工作流批量生产 9:16 竖屏短视频，并给成品加中文字幕。当用户要"批量生成科普/知识类短视频""跑 pika 文生视频工作流""按编号批量出片""给视频加中文字幕""做剪映草稿"时使用。包含已验证的节点图与参数、四段式提示词格式、逐条自动验收（时长/画幅/音轨/黑屏/画面文字检测）与失败重试策略。
agent_created: true
---

# ComfyUI 批量短视频生产

## 用途

把"一次生成一条视频、靠肉眼验收"变成可重复的批处理：用 ComfyUI 的 `/prompt` 接口串行提交，
每条独立提示词、独立保存，生成后自动做技术验收与画面文字检测，不合格自动重试。
跑完再走第二段，把配音识别成字幕并烧进画面（或生成剪映草稿供精修）。

## 何时使用

- 要按编号批量产出竖屏短视频（几十到上百条）
- 要复用本机已跑通的 Pika / MiniMax-H3 文生视频工作流
- 要给已有视频批量加中文字幕、重点词高亮
- 要复核一批成品的时长、分辨率、音轨、有没有画面文字

## 前置检查（每次开工都做）

1. ComfyUI 是否在跑：`curl -s http://127.0.0.1:8200/system_stats`。**端口不一定是 8188**，本机实测 8200。
2. 模型文件是否齐全：对照 `references/workflow-pika-h3-t2v.md` 的模型表。
   工作流 JSON 里写的模型名可能是错的（本机就遇到过），**以界面里跑通的那份为准**。
3. 队列是否为空：非空先等，不要并发提交。
4. 输出目录是否已有同名成品：有就 `--resume` 跳过，别覆盖。

## 第一段：批量生成

```bash
# 1) 准备提示词 JSON（数组，字段见 assets/prompts-template.json）
#    id / filename / title / integrated / soundscape / music / voice / dialogue
#    只有"标题 + 一句话知识点"也行，按 references/content-authoring.md 扩写成六字段

# 2) 提交前校验（不耗显存，几秒出结果）
python scripts/validate_prompts.py --prompts prompts.json

# 3) 先验证一条（最省时间的做法）
python scripts/batch_generate.py --prompts prompts.json --outdir "L:\...\第二批" --ids 21

# 4) 通过后串行跑完整批
python scripts/batch_generate.py --prompts prompts.json --outdir "L:\...\第二批" --ids 21-40

# 中断后续跑
python scripts/batch_generate.py --prompts prompts.json --outdir out --ids 21-40 --resume
```

脚本行为：

- 串行提交，逐条轮询 `/history`，取 `/view` 下载到 `--outdir`
- 每条完成即验收：时长、宽高比、音轨、黑屏/静态、画面文字
- 验收不过自动重试，最多 `--max-attempts` 次；**出现画面文字时自动升级为强"禁止文字"约束**
- 每完成一条写一次 `run_log.json`，中断不丢进度
- 结束时打印成功数、总耗时、平均单条耗时

参数与节点图见 `references/workflow-pika-h3-t2v.md`；提示词写法见 `references/prompt-format.md`。
**不要改已验证的模型、采样、分辨率、帧数**——慢一点不是问题，参数动了要重新验证。

## 第二段：加字幕与包装

轻量（只加字幕，只需 ffmpeg，输出 1080×1920 / 30fps）：

```bash
python scripts/add_subtitles.py --video in.mp4 --cues cues.json --head "5秒涨知识"
python scripts/add_subtitles.py --video in.mp4 --asr asr.json --key 三个心脏 --tail "关注我"
# 源片已是成品规格时不再放大
python scripts/add_subtitles.py --video final.mp4 --asr asr.json --no-scale
```

完整包装（栏目名、重点词高亮、贴纸、音效、剪映草稿）：走工作区已有的 `tools/` 管线，
顺序与坑见 `references/subtitle-pipeline.md`。**优先复用那套工具，不要重写。**

## 两级分辨率（别搞混）

| 阶段 | 分辨率 | 帧率 | 说明 |
|---|---|---|---|
| 生成（ComfyUI 原始输出） | **736×1312**（9:16） | 24fps | 模型原生尺寸，5.17s / 124 帧 |
| 包装（可发布成品） | **1080×1920** | 30fps | H.264 + AAC 44.1kHz，平台规格 |

生成后**不要**直接当成品发布——736×1312 只是中间产物。走第二段 `add_subtitles.py`
（或工作区 `tools/render_video.py`）统一到 1080×1920 / 30fps 才是最终交付规格。

放大方式：`scale=1080:1920:force_original_aspect_ratio=increase` + `crop` + `flags=lanczos`
+ 轻度 `unsharp=0.5`。源 736→1080 是 1.47 倍，lanczos 比默认 bicubic 锐度约高 8%，
锐化再提升边缘观感且不产生光晕。**放大不增加信息量，只为满足平台规格**，不是真高清；
要真正提质只能提高生成分辨率或做 AI 超分（见 `references/subtitle-pipeline.md`）。

## 验收与交付

```bash
# 生成阶段复检（736x1312）
python scripts/verify_video.py --dir "L:\...\第三批" --expect 736x1312

# 成品阶段复检（1080x1920）
python scripts/verify_video.py --dir "output/成品" --expect 1080x1920

# 生成批量生产记录
python scripts/make_report.py --log out/run_log.json --out out/批量生产记录.md
```

`verify_video.py` 退出码 0 表示全部合格，1 表示有不合格项——可直接用于自动化判断。

交付时必须如实报告：成功/失败/待复核数量、总耗时与平均耗时、实际分辨率与帧率、
配音是否完整、失败原因、真实文件路径。**不能凭 ComfyUI 返回 success 就判定成功。**

## 硬性纪律

- 不改工作流参数、不换模型、不装插件、不清插件
- 不覆盖已有成品；命名带系列前缀，避免不同来源都从 `00001` 起编号而互相覆盖
- 串行生产，禁止并发堆积显存
- 配音必须人工听检：自动转写只能辅助，不能作为"配音正确"的唯一依据
- 失败先分析原因再重试，禁止"一失败就改整个工作流"

## 参考文件

| 文件 | 内容 |
|---|---|
| `references/content-authoring.md` | 选题 → 提示词的生产规范、台词长度、选题合规边界 |
| `references/workflow-pika-h3-t2v.md` | 已验证的模型表、参数、节点连接、接口 |
| `references/prompt-format.md` | 四段式提示词格式、中文配音要求、字幕规避 |
| `references/subtitle-pipeline.md` | ASR → 清洗 → ASS → 渲染 → 剪映草稿 |
| `references/troubleshooting.md` | 提交被拒、显存、画面文字、验收不过、续跑 |
| `assets/prompts-template.json` | 提示词 JSON 样例 |
