from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Sequence

from .config import DEFAULT_LLMS, JST, UTC
from .storage import PICKS_DIR, dump_json, load_json_optional, flat_picks_json_path


@dataclass
class LlmPick:
    model: str
    symbols: List[str]
    reasons: List[str]
    picked_at_utc: datetime

    def to_dict(self) -> dict:
        data = asdict(self)
        data["picked_at_utc"] = self.picked_at_utc.astimezone(UTC).isoformat()
        return data


def generate_stub_picks(week_dir: Path, models: Sequence[str] | None = None) -> list[LlmPick]:
    # Placeholder picks. Replace with real LLM calls.
    models = list(models) if models else DEFAULT_LLMS
    base_candidates = [
        "7203.T",  # トヨタ
        "6758.T",  # ソニーＧ
        "9984.T",  # ソフトバンクＧ
        "6861.T",  # キーエンス
        "8035.T",  # 東エレク
        "8306.T",  # 三菱ＵＦＪ
        "8316.T",  # 三井住友ＦＧ
        "9432.T",  # ＮＴＴ
        "4063.T",  # 信越化
        "5401.T",  # 日本製鉄
        "4502.T",  # 武田薬品
        "6098.T",  # リクルートＨＤ
        "2802.T",  # 味の素
        "2914.T",  # ＪＴ
        "3382.T",  # セブン＆アイ
        "9020.T",  # ＪＲ東日本
        "9022.T",  # ＪＲ東海
        "8058.T",  # 三菱商事
        "8267.T",  # イオン
        "5108.T",  # ブリヂストン
        "8001.T",  # 伊藤忠商事
        "6902.T",  # デンソー
        "6981.T",  # 村田製作所
        "6752.T",  # パナソニックＨＤ
        "6501.T",  # 日立製作所
        "7201.T",  # 日産自
        "4503.T",  # アステラス
        "4523.T",  # エーザイ
        "8591.T",  # オリックス
        "6988.T",  # 日東電工
    ]
    picks: list[LlmPick] = []
    now = datetime.now(tz=JST)
    rng = random.Random()
    rng.seed(now.timestamp())
    reason_templates = [
        "直近決算が堅調でガイダンスが前向き",
        "EPS 成長とROEが同業比優位",
        "割安バリュエーション（PER/EVEBITDA）",
        "需給改善と出来高増加が確認できる",
        "配当利回りが市場平均を上回る",
        "構造的なテーマ追い風（半導体/AI）",
    ]
    for model in models:
        symbols = rng.sample(base_candidates, k=2)
        reasons = [rng.choice(reason_templates) for _ in symbols]
        picks.append(LlmPick(model=model, symbols=symbols, reasons=reasons, picked_at_utc=now.astimezone(UTC)))
    save_picks(week_dir, picks)
    return picks


def save_picks(week_dir: Path, picks: Sequence[LlmPick]) -> None:
    PICKS_DIR.mkdir(parents=True, exist_ok=True)
    payload = _picks_to_object(week_dir.name, picks)
    dump_json(flat_picks_json_path(week_dir.name), payload)


def week_dir_from_id(week_id: str) -> Path:
    return PICKS_DIR / week_id


def save_week_and_current(week_id: str, picks: Sequence[LlmPick]) -> None:
    week_dir = week_dir_from_id(week_id)
    save_picks(week_dir, picks)
    dump_json(PICKS_DIR / "current.json", _picks_to_object(week_id, picks))


def load_picks(week_dir: Path) -> list[LlmPick]:
    raw = load_json_optional(flat_picks_json_path(week_dir.name))
    return _object_to_picks(raw)


def load_current_picks() -> list[LlmPick]:
    raw = load_json_optional(PICKS_DIR / "current.json")
    return _object_to_picks(raw)


def _picks_to_object(week_id: str, picks: Sequence[LlmPick]) -> dict:
    if not picks:
        return {"week_start": week_id, "picked_at_utc": None, "picks": {}}
    picked_ts = picks[0].picked_at_utc.astimezone(UTC).isoformat()
    obj: dict[str, object] = {
        "week_start": week_id,
        "picked_at_utc": picked_ts,
        "picks": {},
    }
    for pick in picks:
        entries = []
        for idx, sym in enumerate(pick.symbols):
            entries.append(
                {
                    "symbol": sym,
                    "reason": pick.reasons[idx] if idx < len(pick.reasons) else "",
                    "symbol_index": idx,
                }
            )
        obj["picks"][pick.model] = entries
    return obj


def _object_to_picks(raw) -> list[LlmPick]:
    if not raw:
        return []
    picks_field = raw.get("picks", {}) if isinstance(raw, dict) else {}
    picked_ts = raw.get("picked_at_utc") if isinstance(raw, dict) else None
    picked_dt = datetime.fromisoformat(picked_ts) if picked_ts else datetime.now(tz=UTC)

    picks: list[LlmPick] = []
    for model, entries in picks_field.items():
        symbols: list[str] = []
        reasons: list[str] = []
        # ensure order by symbol_index if present
        if isinstance(entries, list):
            sorted_entries = sorted(
                [e for e in entries if isinstance(e, dict)], key=lambda e: e.get("symbol_index", 0)
            )
            for e in sorted_entries:
                symbols.append(e.get("symbol", ""))
                reasons.append(e.get("reason", ""))
        picks.append(LlmPick(model=str(model), symbols=symbols, reasons=reasons, picked_at_utc=picked_dt))
    return sorted(picks, key=lambda p: p.model)
