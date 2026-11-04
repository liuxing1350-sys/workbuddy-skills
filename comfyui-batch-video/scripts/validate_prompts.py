# -*- coding: utf-8 -*-
"""提交前校验提示词 JSON，避免白跑几分钟才发现文案有问题。

用法：
  python validate_prompts.py --prompts prompts.json
  python validate_prompts.py --prompts prompts.json --max-dialogue 24 --strict
退出码 0 表示通过（可能有警告），1 表示有错误。
"""
import argparse, json, os, re, sys

REQUIRED = ["id", "filename", "integrated", "soundscape", "music", "voice", "dialogue"]
CJK = re.compile(r"[\u4e00-\u9fff]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts", required=True)
    ap.add_argument("--max-dialogue", type=int, default=26, help="中文台词上限字数，默认 26")
    ap.add_argument("--min-dialogue", type=int, default=6, help="中文台词下限字数，默认 6")
    ap.add_argument("--strict", action="store_true", help="把警告也当错误")
    a = ap.parse_args()

    data = json.load(open(a.prompts, encoding="utf-8"))
    if not isinstance(data, list):
        print("提示词文件必须是 JSON 数组"); sys.exit(1)

    errors, warns = [], []
    seen_ids, seen_files = {}, {}

    for i, it in enumerate(data):
        tag = "第%d条(id=%s)" % (i + 1, it.get("id", "?"))

        for k in REQUIRED:
            if not str(it.get(k, "")).strip():
                errors.append("%s 缺少字段 %s" % (tag, k))

        pid = it.get("id")
        if pid in seen_ids:
            errors.append("%s id 与第%d条重复" % (tag, seen_ids[pid] + 1))
        else:
            seen_ids[pid] = i

        fn = str(it.get("filename", ""))
        if fn:
            if not re.match(r"^\d+_[A-Za-z0-9_\-]+\.mp4$", fn):
                errors.append("%s 文件名不合规（应为 编号_英文名.mp4）：%s" % (tag, fn))
            if fn in seen_files:
                errors.append("%s 文件名与第%d条重复：%s" % (tag, seen_files[fn] + 1, fn))
            else:
                seen_files[fn] = i
            if pid is not None and fn and not fn.startswith("%s_" % pid):
                warns.append("%s 文件名编号与 id 不一致：%s" % (tag, fn))

        integ = str(it.get("integrated", ""))
        if integ:
            if CJK.search(integ):
                errors.append("%s integrated 里混入了中文，画面描述必须全英文" % tag)
            if "9:16" not in integ and "vertical" not in integ.lower():
                warns.append("%s integrated 未声明竖屏（Vertical 9:16 composition）" % tag)
            if "one continuous shot" not in integ.lower():
                warns.append("%s integrated 未声明单镜头（One continuous shot）" % tag)

        dlg = str(it.get("dialogue", "")).strip()
        if dlg:
            n = len(re.sub(r"[\s，。！？、,.!?]", "", dlg))
            if n > a.max_dialogue:
                errors.append("%s 台词 %d 字，超过 %d 字上限（5 秒会念不完被截断）：%s"
                              % (tag, n, a.max_dialogue, dlg))
            elif n < a.min_dialogue:
                warns.append("%s 台词只有 %d 字，信息量可能不足" % (tag, n))
            if not CJK.search(dlg):
                errors.append("%s 台词不是中文：%s" % (tag, dlg))

        voice = str(it.get("voice", ""))
        if voice and CJK.search(voice):
            warns.append("%s voice 含中文，建议用英文音色描述" % tag)

    print("共 %d 条" % len(data))
    if warns:
        print("\n警告 %d 条：" % len(warns))
        for w in warns:
            print("  ! " + w)
    if errors:
        print("\n错误 %d 条：" % len(errors))
        for e in errors:
            print("  x " + e)
        sys.exit(1)

    if a.strict and warns:
        print("\n--strict 模式：存在警告即视为不通过")
        sys.exit(1)

    print("\n校验通过，可以提交生成。")


if __name__ == "__main__":
    main()
