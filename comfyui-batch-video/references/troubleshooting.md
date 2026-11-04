# 排错手册

## 一、提交就被拒（HTTP 400）

`/prompt` 在入队前校验，错误信息会直接指出问题，不会白跑。

| 报错关键词 | 原因 | 处置 |
|---|---|---|
| `Value not in list` + 模型名 | 工作流 JSON 里的模型文件名与磁盘不一致 | 以 ComfyUI 界面里跑通的那份为准，别照抄 JSON |
| `Cannot execute because node ... does not exist` | 缺自定义节点 | 不要重装插件，先确认 ComfyUI 版本与节点包 |
| `Required input is missing` | 少传了必填参数 | 对照 `references/workflow-pika-h3-t2v.md` 的参数表 |

**先跑一条 dry-run 提交**是成本最低的验证：参数错立刻报，参数对才排队。

## 二、ComfyUI 连不上

```bash
# 确认端口
netstat -ano | grep LISTEN
# 确认是不是 ComfyUI
curl -s http://127.0.0.1:8200/system_stats
```

端口不一定是 8188，本机实测是 **8200**。若 `/system_stats` 返回 `devices` 数组，就是 ComfyUI。

## 三、生成很慢或卡住

- 单条正常 **2.7—3.5 分钟**，首条约 4 分钟（含模型加载）
- 明显变慢先查显存：`/system_stats` 的 `vram_free`。低于 1GB 会开始换页
- **串行执行**，不要并发提交。并发会让显存堆积，反而更慢甚至 OOM
- 队列非空时不要重复提交同一条，先查 `/queue`

## 四、画面出现字幕 / 文字（高频问题）

**现象**：`Dialogue: "中文台词"` 被模型画成了画面字幕。

**处置**：
1. 用 `subtitle_score()` 检测，`>=2` 判定含文字（有字幕实测 3—21 分，无字幕全为 0）
2. `batch_generate.py` 会自动在重试时追加 `STRONG_NO_TEXT` 强约束
3. 强约束仍失败 → 标记 `NEEDS_REVIEW`，人工改写画面描述：把"需要文字解释"的知识点
   改成纯动作/可视化演示，降低模型"想写字"的倾向
4. 注意：这不是提示词漏写，是模型随机不遵守，同一批里约 8% 会中招，**必须逐条检测**

**别做**：不要因为出现字幕就改工作流参数或换模型——问题在提示词层，不在采样层。

## 五、视频验收不通过

| 现象 | 判定 | 处置 |
|---|---|---|
| 时长 < 4.5s 或 > 6.0s | 帧数/采样异常 | 确认 `length=124`、`fps=24` 没被改 |
| 宽高比不是 0.56 左右 | 分辨率被改成 832×1216 等 | 改回 736×1312 |
| 无音轨 | `VAEDecodeAudio` 没接上 `CreateVideo` | 检查节点 16 → 19 的 audio 连线 |
| 全黑 | 解码失败 / VAE 不匹配 | 确认用 `vae_sol` 解码、`vae_video` 进 H3 |
| 静态画面 | 采样步数被削减 | 恢复 sigmas 的 6 步配置 |

## 六、配音无法自动校验

本机 ComfyUI 的 `Qwen3ASRTranscriber` 节点有 bug（`Qwen3ASRConfig` 缺属性），
在工作流里跑 ASR 会直接报错，与视频质量无关。

**替代方案**：用工作区 `tools/asr_transcribe.py`（faster-whisper + GPU）离线识别成品音轨，
再按 `references/subtitle-pipeline.md` 的清洗规则处理。配音是否完整、有没有改知识点，
最终仍需人工听一遍——自动转写只能辅助。

## 七、批量中断后如何续跑

`batch_generate.py` 每完成一条就写一次 `run_log.json`。中断后用 `--resume` 续跑，
已存在且验收通过的文件会跳过，不会重复生成。

```bash
python batch_generate.py --prompts prompts.json --outdir out --ids 41-90 --resume
```

## 八、路径与环境

- Windows 下 ffmpeg/ffprobe 常不在 PATH。ComfyUI 便携版自带：
  `python_embeded/Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg.exe` 与
  `.../torchcodec/ffprobe.exe`，`load_config()` 会自动探测
- ASS 字幕烧录时路径要转义：反斜杠改正斜杠、盘符冒号前加 `\:`（`add_subtitles.py` 已处理）
- 中文字幕文件建议存 `utf-8-sig`，避免部分播放器首行乱码
