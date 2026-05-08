"""
ギャップスコアの算出。

設計方針:
  - 単独モジュールに切り出し、後で式を調整しやすくする
  - 素朴版 + 「片側欠損ブースト」を持つ
  - 0 〜 ~10 の range に収まるよう log を使う

素朴な式:
  base_gap = log(max(en_pv, ja_pv) + 1) * size_imbalance
  size_imbalance = 1 - min(en_bytes, ja_bytes) / max(en_bytes, ja_bytes, 1)

完全ギャップ (片側欠損):
  bigger 側の bytes と pv に依存して大きなブーストを与える。
  これにより「英語版に大きな記事があるが日本語版が無い」記事が
  上位に来る (= まさに翻訳すべき対象)。
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class GapInputs:
    en_bytes: int | None
    ja_bytes: int | None
    en_pv_90d: int | None
    ja_pv_90d: int | None


def gap_score(inputs: GapInputs) -> float:
    en_b = max(0, inputs.en_bytes or 0)
    ja_b = max(0, inputs.ja_bytes or 0)
    en_pv = max(0, inputs.en_pv_90d or 0)
    ja_pv = max(0, inputs.ja_pv_90d or 0)

    max_pv = max(en_pv, ja_pv)
    pv_factor = math.log(max_pv + 1)

    # 片側完全欠損: 大きい側の bytes をブースト寄与に
    if en_b == 0 and ja_b == 0:
        return 0.0
    if en_b == 0 or ja_b == 0:
        bigger = max(en_b, ja_b)
        # bytes を log スケールで (大きい記事ほど翻訳価値大)
        size_factor = math.log(bigger + 1)
        boost = 2.0  # 完全ギャップは × 2
        return round(pv_factor * size_factor * boost / 10.0, 4)

    # 両方ある: bytes 比のアンバランス
    smaller = min(en_b, ja_b)
    bigger = max(en_b, ja_b)
    size_imbalance = 1.0 - (smaller / bigger)
    # 大きい側の絶対サイズも掛ける (大記事のギャップを優先)
    size_factor = math.log(bigger + 1)
    return round(pv_factor * size_factor * size_imbalance / 10.0, 4)


__all__ = ["GapInputs", "gap_score"]
