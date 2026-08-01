"""音源プロファイル。現状 KSOP のみ。VSOP は Phase 3。"""

from . import ksop

PROFILES = {
    "ksop": ksop,
}


def get(name: str):
    try:
        return PROFILES[name]
    except KeyError:
        known = ", ".join(sorted(PROFILES))
        raise KeyError(f"未知のプロファイル: {name!r}（利用可能: {known}）") from None
