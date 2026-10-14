"""档位路由：把调用方请求的 model 解析成有序候选模型链。"""

from dataclasses import dataclass

from .config import get_settings, load_yaml


@dataclass
class Tier:
    name: str
    display_name: str
    models: list[str]


def load_tiers() -> dict[str, Tier]:
    conf = load_yaml("tiers.yaml")
    tiers: dict[str, Tier] = {}
    for name, spec in (conf.get("tiers") or {}).items():
        models = [str(m) for m in (spec.get("models") or []) if str(m)]
        if not models:
            continue
        tiers[str(name)] = Tier(
            name=str(name), display_name=spec.get("display_name") or str(name), models=models
        )
    return tiers


def resolve_candidates(requested: str | None, tiers: dict[str, Tier] | None = None):
    """返回 (tier_name, candidates)。

    - 请求的是档位别名 → 该档位的完整链；
    - 请求的是具体模型且属于某档位 → 它打头 + 同档其余模型按序回退；
    - 其他 → 原样直连（单元素链）。
    """
    tiers = tiers if tiers is not None else load_tiers()
    requested = (requested or "").strip()
    if not requested:
        return None, []
    if requested in tiers:
        return requested, list(tiers[requested].models)
    for tier in tiers.values():
        if requested in tier.models:
            rest = [m for m in tier.models if m != requested]
            return None, [requested, *rest]
    return None, [requested]


def tier_display_name(name: str | None) -> str | None:
    if not name:
        return None
    tiers = load_tiers()
    return tiers[name].display_name if name in tiers else name


def find_tier_of(model: str, tiers: dict[str, Tier] | None = None) -> str | None:
    tiers = tiers if tiers is not None else load_tiers()
    for tier in tiers.values():
        if model in tier.models:
            return tier.name
    return None
