# -*- coding: utf-8 -*-
"""把 run_log.json 转成 Markdown 批量生产记录。

用法：
  python make_report.py --log out/run_log.json --out out/批量生产记录.md --workflow pika_文生视频.json
"""
import argparse, json, os


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workflow", default="pika_文生视频.json")
    ap.add_argument("--title", default="儿童科普视频 批量生产记录")
    a = ap.parse_args()

    log = json.load(open(a.log, encoding="utf-8"))
    rows, total = [], 0.0
    succ = fail = review = 0
    for k in sorted(log, key=lambda x: int(x)):
        r = log[k]
        p = r.get("probe", {}) or {}
        el = r.get("elapsed_sec", 0) or 0
        total += el
        st = r.get("status")
        if st == "SUCCESS": succ += 1
        elif st == "NEEDS_REVIEW": review += 1
        else: fail += 1
        rows.append((r.get("id"), r.get("title", ""), round(el / 60, 1),
                     p.get("dur", "-"), "%sx%s" % (p.get("w"), p.get("h")) if p.get("w") else "-",
                     p.get("fps", "-"), "有" if p.get("has_audio") else "无",
                     r.get("subtitle_rows", "-"),
                     "成功" if st == "SUCCESS" else ("待复核" if st == "NEEDS_REVIEW" else "失败"),
                     r.get("file", "-")))

    L = []
    L.append("# %s\n" % a.title)
    L.append("- 工作流：%s（纯文生视频，MiniMax-H3 + Pika turbo 8step LoRA）" % a.workflow)
    L.append("- 分辨率/帧率：736x1312（9:16）/ 24fps，时长约 5.17s（124 帧）")
    L.append("- 成功：%d　失败：%d　待复核：%d" % (succ, fail, review))
    n = max(1, len(log))
    L.append("- 总耗时：%.1f 分钟；平均单条：%.1f 分钟\n" % (total / 60, total / 60 / n))
    L.append("| 编号 | 视频名称 | 工作流 | 生成耗时(分) | 时长(s) | 分辨率 | 帧率 | 配音 | 画面文字行 | 验收状态 | 文件路径 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        L.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" %
                 (r[0], r[1], a.workflow, r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9]))
    L.append("")
    L.append("> 画面文字行 <2 视为无字幕；配音由模型在生成时直接合成，需人工听检确认台词完整准确。")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    open(a.out, "w", encoding="utf-8").write("\n".join(L))
    print("已生成 %s（成功 %d / 失败 %d / 待复核 %d）" % (a.out, succ, fail, review))


if __name__ == "__main__":
    main()
