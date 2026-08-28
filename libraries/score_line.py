"""Pure score-line calculation shared by the command and unit tests."""


def calculate_score_line(music, level_index: int, line: float, labels=None) -> str:
    if level_index < 0 or level_index >= len(music.charts) or not 0 < float(line) < 101:
        raise ValueError("目标达成率必须在 0 到 101 之间，并选择存在的难度")
    notes = music.charts[level_index].notes
    tap = int(getattr(notes, "tap", 0)); hold = int(getattr(notes, "hold", 0))
    slide = int(getattr(notes, "slide", 0)); touch = int(getattr(notes, "touch", 0))
    brk = int(getattr(notes, "brk", 0))
    total_score = tap * 500 + slide * 1500 + hold * 1000 + touch * 500 + brk * 2500
    if total_score <= 0:
        raise ValueError("该谱面没有有效的音符统计")
    reduce = 101 - float(line)
    great_count = total_score * reduce / 10000
    per_great = 10000 / total_score
    if brk:
        break_50_reduce = total_score * (0.01 / brk) / 4
        break_text = (
            f"BREAK 50 落（共 {brk} 个）\n"
            f"等价于 {break_50_reduce / 100:.3f} 个 TAP GREAT"
            f"（-{break_50_reduce / total_score * 100:.4f}%）"
        )
    else:
        break_text = "该谱面没有 BREAK，暂无 BREAK 50 落换算。"
    labels = labels or ["Basic", "Advanced", "Expert", "Master", "Re:Master"]
    label = labels[level_index] if level_index < len(labels) else f"难度 {level_index + 1}"
    return (
        f"{music.title}「{label}」\n"
        f"分数线「{float(line):g}%」\n"
        f"允许的最多 TAP GREAT 数量：{great_count:.2f}（每个 -{per_great:.4f}%）\n"
        f"{break_text}"
    )
