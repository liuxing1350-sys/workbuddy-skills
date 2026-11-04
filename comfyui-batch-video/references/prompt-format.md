# 提示词格式：四段式单节点 + 中文配音

工作流只有一个文本输入节点（节点 9 的 `prompt`）。画面、音效、配乐、台词**必须拼进同一个字符串**，
按下面的顺序和分隔标题书写——这个结构是模型能同时理解画面与语音的关键，不要拆成多段或改写标题。

## 一、标准结构

```
<integrated_multimodal_description 英文画面描述>

overall_soundscape
<英文音效描述>

non_diegetic_music
<英文配乐描述>

voiceover
Language: Mandarin Chinese.
Voice: <英文音色描述>
Dialogue: "<中文台词>"

No subtitles, no visible text, no logos.
```

对应提示词 JSON 的字段：

| 字段 | 内容 |
|---|---|
| `integrated` | 英文画面描述，含 9:16 竖屏、单镜头、0–2s / 2–5s 动作分镜 |
| `soundscape` | 英文环境音效 |
| `music` | 英文背景音乐风格 |
| `voice` | 英文音色描述（如 `Cheerful children's science narrator.`） |
| `dialogue` | **中文普通话台词**，逐字使用给定文本，不改写知识点 |

## 二、画面描述写法

- 开头点明主体、场景、`Vertical 9:16 composition. One continuous shot.`
- 用 `0–2 seconds:` / `2–5 seconds:` 划动作节奏（注意是 en dash `–`，不是连字符）
- 结尾补风格词：`Cute high-quality 3D educational animation, bright colors, child-safe.`
- 需要可视化知识点时，用"show a gentle educational visualization of ..."这类句式，比抽象描述更稳

## 三、中文配音要求

- 音色：儿童科普女声或亲切活泼的普通话讲解声，语速适中
- 台词：**5 秒内说完**，一句话讲清一个知识点，通常 15—25 个汉字最稳
- 不得改写科学结论、不得加无关台词
- 音频是模型合成，无法逐字校验；台词过长会被截断，宁可短

## 四、画面文字（字幕）问题——最容易翻车的地方

模型有时会把 `Dialogue` 里的中文台词**直接烧成画面字幕**，违反"无字幕"要求。
实测在 50 条里出现 4 条（约 8%），且与题材无关、随机发生。

**成因**：`Dialogue: "中文"` 这行文本本身就是画面文字信号，约束越弱越容易被画出来。

**处置阶梯**（`batch_generate.py` 已内置自动升级）：

1. 第 1 次：标准约束 `No subtitles, no visible text, no logos.`
2. 第 2 次起：追加 `STRONG_NO_TEXT`（见 `comfy_h3.py`），显式列出 no captions / no letters /
   no numbers / dialogue is audio only 等，并强调 `Keep the image completely free of any text-like graphic.`
3. 仍失败：标记 `NEEDS_REVIEW`，交人工决定是否改写画面描述（例如把知识点可视化改为纯动作演示，
   降低"需要文字解释"的倾向）

**必须做自动检测**：不要凭 ComfyUI 返回 success 就验收。用 `subtitle_score()` 抽 6 帧判分，
`>=2` 即判定画面含文字。实测该指标对"有字幕"给 3—21 分、"无字幕"全部为 0，区分度足够。

## 五、其他负面要求

- 不生成水印、Logo、字幕
- 避免出现真实品牌名、屏幕文字、书籍封面等容易诱发伪文字的物体
- 单镜头，不要切镜
