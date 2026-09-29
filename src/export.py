"""
Puanlama bittikten sonra araştırmacı Excel çıktıları.

Beş dosya üretilir: yanıtlar, geniş puan, uzun puan, okunabilirlik ve özet.
Bu dosyalar model kimliği içerir; uzman arayüzüne girmez.
"""

import json
from pathlib import Path

import pandas as pd

from src.database import ENGINE
from src.domain import CAS_ITEMS, DISCERN_ITEMS

SCORE_VALUE_COLUMNS = [
    "gqs",
    "checklist_pct",
    "checklist_weighted_pct",
    "cas_food",
    "cas_religion",
    "cas_health_system",
    "cas_local",
    "cas_cultural",
    "cas_total",
    "safety_issue",
    "discern_purpose",
    "discern_relevance",
    "discern_sources",
    "discern_uncertainty",
    "discern_alternatives",
    "discern_risks",
    "discern_physician_ref",
    "discern_balance",
    "discern_total",
]

IDENTITY_COLUMNS = [
    "response_id",
    "blind_code",
    "question_id",
    "axis",
    "question_type",
    "sub_theme",
    "model_id",
    "provider",
    "model_string",
    "repetition",
]


def export_all(output_dir: Path) -> list[Path]:
    """Beş Excel dosyasını yazar ve yollarını döndürür."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    responses = _read_sql(_RESPONSES_SQL)
    scores = _read_sql(_SCORES_SQL)
    readability = _read_sql(_READABILITY_SQL)

    targets = {
        "responses_full.xlsx": responses,
        "scores_wide.xlsx": _scores_wide(responses, scores),
        "scores_long.xlsx": _scores_long(scores),
        "readability.xlsx": readability,
        "summary_stats.xlsx": None,
    }
    written: list[Path] = []
    for name, frame in targets.items():
        path = output_dir / name
        if name == "summary_stats.xlsx":
            _write_summary(path, scores, readability)
        else:
            frame.to_excel(path, index=False)
        written.append(path)
    return written


def _scores_wide(responses: pd.DataFrame, scores: pd.DataFrame) -> pd.DataFrame:
    """Her yanıt bir satır, uzman puanları sütunlarda."""
    base_columns = [column for column in IDENTITY_COLUMNS if column in responses.columns]
    base = responses[base_columns].drop_duplicates(subset=["response_id"])
    if scores.empty:
        return base
    wide = base
    for evaluator_id, group in scores.groupby("evaluator_id"):
        columns = [column for column in SCORE_VALUE_COLUMNS if column in group.columns]
        slim = group[["response_id", *columns]].copy()
        slim = slim.rename(columns={column: f"{evaluator_id}_{column}" for column in columns})
        wide = wide.merge(slim, on="response_id", how="left")
    return wide


def _scores_long(scores: pd.DataFrame) -> pd.DataFrame:
    """R analizi için yanıt × uzman × ölçek × madde biçimi."""
    rows: list[dict] = []
    if scores.empty:
        return pd.DataFrame(
            columns=[*IDENTITY_COLUMNS, "evaluator_id", "scale", "item", "value", "safety_note"]
        )
    for record in scores.to_dict(orient="records"):
        identity = {column: record.get(column) for column in IDENTITY_COLUMNS}
        identity["evaluator_id"] = record["evaluator_id"]
        rows.append({**identity, "scale": "GQS", "item": "gqs", "value": record["gqs"], "safety_note": None})
        rows.extend(_checklist_rows(record, identity))
        for item in CAS_ITEMS:
            rows.append(_point(identity, "CAS", item.key, record[item.key]))
        rows.append(_point(identity, "CAS", "cas_total", record["cas_total"]))
        rows.append(
            {
                **identity,
                "scale": "SAFETY",
                "item": "safety_issue",
                "value": int(bool(record["safety_issue"])),
                "safety_note": record.get("safety_note"),
            }
        )
        for item in DISCERN_ITEMS:
            rows.append(_point(identity, "DISCERN", item.key, record[item.key]))
        rows.append(_point(identity, "DISCERN", "discern_total", record["discern_total"]))
        for summary in ("checklist_pct", "checklist_weighted_pct"):
            if record.get(summary) is not None:
                rows.append(_point(identity, "CHECKLIST", summary, record[summary]))
    return pd.DataFrame(rows)


def _checklist_rows(record: dict, identity: dict) -> list[dict]:
    """Checklist JSON'unu uzun biçime açar."""
    try:
        checklist = json.loads(record.get("checklist_json") or "{}")
    except json.JSONDecodeError:
        checklist = {}
    return [
        _point(identity, "CHECKLIST", item_id, int(bool(checked)))
        for item_id, checked in checklist.items()
    ]


def _point(identity: dict, scale: str, item: str, value) -> dict:
    """Tek bir ölçek maddesi satırı üretir."""
    return {**identity, "scale": scale, "item": item, "value": value, "safety_note": None}


def _write_summary(path: Path, scores: pd.DataFrame, readability: pd.DataFrame) -> None:
    """Model, eksen ve soru tipine göre tanımlayıcı istatistikleri yazar."""
    with pd.ExcelWriter(path) as writer:
        _summary_sheet(scores, ["provider"]).to_excel(writer, sheet_name="scores_by_model", index=False)
        _summary_sheet(scores, ["axis"]).to_excel(writer, sheet_name="scores_by_axis", index=False)
        _summary_sheet(scores, ["question_type"]).to_excel(writer, sheet_name="scores_by_type", index=False)
        _summary_sheet(readability, ["provider"], _READABILITY_METRICS).to_excel(
            writer, sheet_name="readability_by_model", index=False
        )
        _summary_sheet(readability, ["axis"], _READABILITY_METRICS).to_excel(
            writer, sheet_name="readability_by_axis", index=False
        )
        _summary_sheet(readability, ["question_type"], _READABILITY_METRICS).to_excel(
            writer, sheet_name="readability_by_type", index=False
        )


def _summary_sheet(
    frame: pd.DataFrame,
    group_columns: list[str],
    metrics: list[str] | None = None,
) -> pd.DataFrame:
    """Grup ve ölçüm başına n, ortalama, SS, medyan ve IQR hesaplar."""
    metrics = metrics or [
        "gqs",
        "cas_total",
        "discern_total",
        "checklist_pct",
        "checklist_weighted_pct",
    ]
    if frame.empty or any(column not in frame.columns for column in group_columns):
        return pd.DataFrame(columns=[*group_columns, "metric", "n", "mean", "sd", "median", "iqr"])
    rows = []
    for metric in metrics:
        if metric not in frame.columns:
            continue
        grouped = frame.groupby(group_columns, dropna=False)[metric]
        for key, series in grouped:
            values = series.dropna()
            if not isinstance(key, tuple):
                key = (key,)
            row = dict(zip(group_columns, key))
            row.update(
                {
                    "metric": metric,
                    "n": int(values.count()),
                    "mean": _round(values.mean()) if len(values) else None,
                    "sd": _round(values.std()) if len(values) > 1 else None,
                    "median": _round(values.median()) if len(values) else None,
                    "iqr": _round(values.quantile(0.75) - values.quantile(0.25)) if len(values) else None,
                }
            )
            rows.append(row)
    return pd.DataFrame(rows)


def _round(value) -> float | None:
    """Sayıyı iki basamağa yuvarlar. Boş değerde None döner."""
    if pd.isna(value):
        return None
    return round(float(value), 2)


def _read_sql(query: str) -> pd.DataFrame:
    """Sorguyu DataFrame olarak okur. Tablo yoksa boş çerçeve döner."""
    try:
        return pd.read_sql_query(query, ENGINE)
    except Exception:
        return pd.DataFrame()


def main() -> None:
    """Çıktıları exports/ klasörüne yazar."""
    root = Path(__file__).resolve().parent.parent
    written = export_all(root / "exports")
    for path in written:
        print(path)


_RESPONSES_SQL = """
SELECT r.response_id, r.blind_code, r.question_id, r.model_id, r.repetition,
       r.response_text, r.timestamp, r.tokens_used, r.latency_ms, r.model_version_returned,
       r.finish_reason,
       q.axis, q.type AS question_type, q.sub_theme, q.question_text,
       m.provider, m.model_string, m.reasoning_effort
FROM responses r
JOIN questions q ON r.question_id = q.question_id
JOIN models m ON r.model_id = m.model_id
ORDER BY r.response_id
"""

_SCORES_SQL = """
SELECT s.*, r.blind_code, r.question_id, r.model_id, r.repetition,
       q.axis, q.type AS question_type, q.sub_theme,
       m.provider, m.model_string
FROM scores s
JOIN responses r ON s.response_id = r.response_id
JOIN questions q ON r.question_id = q.question_id
JOIN models m ON r.model_id = m.model_id
ORDER BY s.score_id
"""

_READABILITY_SQL = """
SELECT rd.*, r.blind_code, r.question_id, r.model_id, r.repetition,
       q.axis, q.type AS question_type, m.provider, m.model_string
FROM readability rd
JOIN responses r ON rd.response_id = r.response_id
JOIN questions q ON r.question_id = q.question_id
JOIN models m ON r.model_id = m.model_id
ORDER BY rd.response_id
"""

_READABILITY_METRICS = ["atesman_score", "bezirci_yilmaz_grade", "word_count", "sentence_count"]


if __name__ == "__main__":
    main()
