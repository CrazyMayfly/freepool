"""用控制台 free-quota 页面抓到的真实数据校准额度账本。

用法：.venv/bin/python scripts/calibrate_from_console.py
- 写入每模型 total/effective_from(=到期-90天)/used_offset(=控制台已用-代理已计量)
- 档位中不在「有额度」名单的模型标记 exhausted
- 同步重写 config/free_models.yaml（保留真实起算日，重启再播种也不丢）
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

from app.db import SessionLocal, init_db
from app.models import QuotaRule, UsageRecord
from app import quota

BASE = Path(__file__).resolve().parent.parent

# 从控制台 free-quota 页面抄录你账号的实际数据后运行本脚本：
#   打开 https://bailian.console.aliyun.com/cn-beijing/costing-balance/free-quota
#   （分页调到 100 条/页更方便），把"有额度"的模型逐行填入下面的 CONSOLE 列表。
# 仅收录 token 计量的模型（如 共 1M）；图片/视频按张数、语音按秒的额度与代理计量单位不符，不导入。
# remaining 支持 "1M" / "523.83K" / 纯数字（tokens）。
CONSOLE = [
    # {"model": "qwen3.8-flash", "remaining": "523.83K", "expires": "2026/11/25"},
    # {"model": "deepseek-v4.1-flash", "remaining": "1M", "expires": "2026/12/13"},
    # {"model": "kimi-k3", "remaining": "758.46K", "expires": "2026/11/18"},
]

# 你配置在 config/tiers.yaml 里的所有档位模型：不在上面 CONSOLE 名单里的会被标记为耗尽
# （触发档位自动切换）。请按你的 tiers.yaml 实际内容维护。
TIER_MODELS = {
    "qwen3.8-flash", "qwen3.7-flash", "qwen3.7-flash-2026-07-15",
    "deepseek-v4.1-flash", "deepseek-v4-flash-0731",
    "qwen3.8-27b", "qwen3.8-2.4t-a95b", "qwen3.8-omni-flash",
    "qwen3.8-max", "qwen3.8-max-0902", "qwen3.7-max",
    "deepseek-v4-pro", "deepseek-v4-pro-0813", "glm-5.3", "kimi-k3",
    "qwen3.7-plus", "qwen3.8-plus", "qwen-plus",
}

# 档位链上的模型若不在「有额度」名单 → 耗尽/过期
TIER_MODELS = {
    "qwen3.8-flash", "qwen3.7-flash", "qwen3.7-flash-2026-07-15",
    "deepseek-v4.1-flash", "deepseek-v4-flash-0731",
    "qwen3.8-27b", "qwen3.8-2.4t-a95b", "qwen3.8-omni-flash",
    "qwen3.8-max", "qwen3.8-max-0902", "qwen3.7-max",
    "deepseek-v4-pro", "deepseek-v4-pro-0813", "glm-5.3", "kimi-k3",
    "qwen3.7-plus", "qwen3.8-plus", "qwen-plus",
}

VALID_DAYS = 90


def parse_amount(s: str) -> int:
    s = s.strip()
    if s.endswith("M"):
        return int(float(s[:-1]) * 1_000_000)
    if s.endswith("K"):
        return int(float(s[:-1]) * 1_000)
    return int(float(s))


def parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y/%m/%d").date()


def metered(db, model: str) -> int:
    row = db.execute(
        select(func.coalesce(func.sum(UsageRecord.total_tokens), 0)).where(
            UsageRecord.actual_model == model
        )
    ).scalar()
    return int(row)


def main():
    if not CONSOLE:
        raise SystemExit(
            "CONSOLE 列表为空：请先在脚本顶部填入你账号在控制台 free-quota 页面的真实数据"
        )
    init_db()
    results = []
    with SessionLocal() as db:
        for row in CONSOLE:
            model = row["model"]
            total = 1_000_000
            remaining = parse_amount(row["remaining"])
            expires = parse_date(row["expires"])
            effective_from = expires - timedelta(days=VALID_DAYS)
            console_used = total - remaining
            offset = max(0, console_used - metered(db, model))
            quota.upsert_rule(
                db,
                model,
                total_tokens=total,
                effective_from=effective_from,
                valid_days=VALID_DAYS,
                used_offset=offset,
                exhausted=False,
            )
            results.append(
                {"model": model, "total": total, "remaining": remaining,
                 "effective_from": effective_from.isoformat(), "offset": offset}
            )

        active = {r["model"] for r in CONSOLE}
        for model in sorted(TIER_MODELS - active):
            quota.upsert_rule(db, model, exhausted=True)
            results.append({"model": model, "marked": "exhausted"})

    # 重写 free_models.yaml，保留真实起算日
    lines = [
        "# 免费额度种子（2026-10-14 用控制台 free-quota 页面校准）",
        "# effective_from = 到期日 - 90 天；remaining 为校准时的控制台剩余量",
        "default_total_tokens: 1000000",
        "default_valid_days: 90",
        "default_effective_from: null",
        "models:",
    ]
    by_model = {r["model"]: r for r in results}
    for row in CONSOLE:
        r = by_model[row["model"]]
        lines.append(
            f"  {row['model']}: {{effective_from: {r['effective_from']}}}"
        )
    (BASE / "config" / "free_models.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps(results, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
