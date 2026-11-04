# pika_文生视频 工作流：真实参数与节点图

本文件记录已实测跑通的 ComfyUI 图结构。`scripts/comfy_h3.py` 的 `build_prompt()` 与之一一对应，
无需再解析 UI 格式 JSON。

## 一、模型文件（必须与 ComfyUI 可选列表完全一致）

| 角色 | 文件名 |
|---|---|
| UNETLoader | `minimax_h3_fl2va_pruned_int8_convrot.safetensors` |
| LoraLoaderModelOnly | `pika_h3_flex_turbo_8step_hd_fl2va.safetensors`（strength_model=1.0） |
| CLIPLoader | `qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors`，type=`minimax` |
| VAELoader（视频解码） | `minimax_h3_sol_vae_int8_convrot.safetensors` |
| VAELoader（H3 输入） | `minimax_h3_video_vae_int8_convrot.safetensors` |
| VAELoader（音频解码） | `minimax_h3_audio_vae_fp32.safetensors` |

> **关键坑**：仓库里的 `pika_文生视频.json` 写的模型名是 `pika_h3_flex_fl2va_v1_bf16.safetensors`
> 和 `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors`，这两个文件在磁盘上**不存在**，直接提交会报
> 模型缺失。以用户在 ComfyUI 界面里跑通的那份配置为准，不要照抄 JSON。

## 二、生成参数（已验证，不要改）

| 参数 | 值 | 说明 |
|---|---|---|
| width × height | 736 × 1312 | 9:16 竖屏，w/h=0.5610 |
| length | 124 帧 | 24fps → 5.17 秒 |
| fps | 24 | CreateVideo 节点 |
| sampler | `lcm` | KSamplerSelect |
| sigmas | `1.0, 0.972973, 0.923077, 0.8, 0.571429, 0.333333, 0.0` | 6 步，ManualSigmas |
| seed | 固定值（默认 20261030） | RandomNoise |
| BlockSparseAttention | selection=`sol-attn`, tau=1.3, start=0, end=1, min_tokens=12288, extra_tokens=256, sink_conditioning=`exact_kv_and_rows` | 稀疏注意力 |

> 仓库 JSON 里的分辨率是 832×1216（2:3），不是 9:16，必须按上表覆盖。

## 三、节点连接关系

```
2 UNETLoader ──> 3 LoraLoaderModelOnly ──> 10 BlockSparseAttention ──> 11 BasicGuider
4 CLIPLoader ─┐                                                            │
5 VAELoader ──┴─> 9 MiniMaxH3ImageToVideo ──[conditioning]──────────────────┘
                    │  └─[latent]─┐
12 RandomNoise ─────┼────────────┼──> 15 SamplerCustomAdvanced
13 KSamplerSelect ──┼────────────┤         ├─> 16 VAEDecodeAudio (vae=6)
14 ManualSigmas ────┴────────────┘         └─> 18 VAEDecode      (vae=17)
                                               └─> 19 CreateVideo (audio=16) ─> 20 SaveVideo
```

- 节点 9 的 `first_frame` / `last_frame` 输入**悬空**——这是纯文生视频，不需要任何图片。
- 音频由模型在生成时直接合成，经 `VAEDecodeAudio` 解码后并入 `CreateVideo`，**不需要额外 TTS**。

## 四、提交与产物

- 接口：`POST /prompt`，body 为 `{"prompt": <api图>, "client_id": "..."}`
- 轮询：`GET /history/<prompt_id>`，`status.status_str` 为 `success`/`error` 即结束
- 取件：`GET /view?filename=...&subfolder=...&type=output`
- 输出前缀：`video/Pika_H3_Flex_T2V`，落在 `<ComfyUI>/output/video/`
- 单条耗时：首条约 4 分钟（含模型加载），稳定后约 2.7—3.5 分钟

> **注意**：这里产出的是 **736×1312 / 24fps** 的中间片，不是最终交付规格。
> 可发布成品要再经包装阶段统一为 **1080×1920 / 30fps / AAC 44.1kHz**，
> 见 `references/subtitle-pipeline.md`。

## 五、提交前自检

`POST /prompt` 会在入队前校验节点与模型，参数错误会立刻返回 HTTP 400 并指明缺哪个文件，
不会白跑几分钟。因此**先用一条做 dry-run 提交**是成本最低的验证手段。
