"""Section visibility resolution (补齐路线第一批 §7.1，板块可见性).

PlatformOption key ``nav.section_visibility``：{role: [viewId,…]}。
- 未配置（缺省 {}）= 现状全可见（行为不变）；
- 配置后按角色收敛：被配置的角色只可见列出的板块；未配置的角色保持全可见；
- admin 永远全可见；
- portal 恒在（登录后首页兜底，不允许收敛掉）。
"""

from sqlalchemy.orm import Session

from app.models.platform_option import get_option

SECTION_VISIBILITY_OPTION_KEY = "nav.section_visibility"
# 别名（api/platform_security.py 引用简名）
SECTION_VISIBILITY_KEY = SECTION_VISIBILITY_OPTION_KEY

VIEW_IDS = ("portal", "algo", "agent", "quality", "infra", "admin")

# portal 是登录落点，恒保留；收敛配置只对其余板块生效
ALWAYS_VISIBLE_VIEWS = ("portal",)


def resolve_visible_views(db: Session, role: str | None) -> list[str]:
    if role == "admin":
        return list(VIEW_IDS)
    config = get_option(db, SECTION_VISIBILITY_OPTION_KEY, {}) or {}
    if not isinstance(config, dict) or not config:
        return list(VIEW_IDS)
    allowed = config.get(str(role or ""), None)
    if allowed is None:
        # 未配置的角色保持现状全可见
        return list(VIEW_IDS)
    if not isinstance(allowed, (list, tuple)):
        return list(VIEW_IDS)
    visible = [view for view in VIEW_IDS if view in allowed]
    for view in ALWAYS_VISIBLE_VIEWS:
        if view not in visible:
            visible.insert(0, view)
    return visible
