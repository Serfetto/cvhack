"""Графики технической документации → docs/img/chart_*.png. Нужен matplotlib (в сервисах он не используется).

    python docs/make_charts.py

Числа — замеры конвейера на стенде LinQ 24.10.2026 (backend/ml/worker/README.md и Prometheus,
метрика inference_seconds по стадиям); они же приведены таблицей в DOCUMENTATION.md §9.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

OUT = Path(__file__).resolve().parent / "img"

SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
# категориальные слоты 1–3 эталонной палитры (проверены валидатором: CVD ΔE ≥ 9,2)
TPU, CPU, NET = "#2a78d6", "#1baf7a", "#eb6834"

# средняя задержка кадра, мс: TPU вместе с общей очередью стенда · пред- и постобработка на CPU воркера · сеть VPN и брокер
LATENCY = [
    ("pose, 4 камеры", 358, 19, 118),
    ("pose + objects, 4 камеры", 532, 37, 266),
    ("pose + objects, 7 камер", 721, 68, 161),
]


def latency_chart() -> None:
    plt.rcParams.update({"font.family": ["Segoe UI", "DejaVu Sans"], "font.size": 10})
    fig, ax = plt.subplots(figsize=(9, 3.1), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    rows = list(reversed(LATENCY))
    for y, (label, tpu, cpu, net) in enumerate(rows):
        left = 0
        for value, color in ((tpu, TPU), (cpu, CPU), (net, NET)):
            # белая кромка — зазор 2 px между сегментами
            ax.barh(y, value, left=left, height=0.5, color=color, edgecolor=SURFACE, linewidth=2)
            if value >= 60:
                ax.text(left + value / 2, y, f"{value}", ha="center", va="center", color="#ffffff" if color == TPU else INK,
                        fontsize=9, fontweight="semibold")
            left += value
        ax.text(left + 12, y, f"{left} мс", ha="left", va="center", color=INK, fontsize=10, fontweight="semibold")
    ax.set_yticks(range(len(rows)), [r[0] for r in rows], color=INK)
    ax.set_xlim(0, 1050)
    ax.set_xlabel("средняя задержка кадра, мс", color=MUTED)
    ax.tick_params(axis="x", colors=MUTED, length=0)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in (TPU, CPU, NET)]
    ax.legend(handles, ["TPU с очередью стенда", "пред- и постобработка (CPU воркера)", "сеть VPN и брокер"],
              loc="lower left", bbox_to_anchor=(0, 1.02), ncol=3, frameon=False, fontsize=9, labelcolor=INK,
              handlelength=1, handleheight=1)
    fig.tight_layout()
    fig.savefig(OUT / "chart_latency.png", facecolor=SURFACE)
    plt.close(fig)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    latency_chart()
    print(OUT / "chart_latency.png")
