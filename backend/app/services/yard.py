"""堆场管理业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "yard"
REQUIRED_FIELDS = ["箱区编号", "箱区名称", "堆放层数"]
STATUS_ORDER = ["待启用", "正常堆放", "接近满载", "已封闭"]
ACTION_RULES = {"启用箱区": "正常堆放", "封闭箱区": "已封闭", "腾空箱区": "待启用"}
NEGATIVE_ACTIONS = []


def _as_number(value: Any) -> float | None:
    """把箱位、层数这类字段尽量读成数字；读不出来就返回 None，不参与对账。"""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _present(row: dict[str, Any]) -> dict[str, Any]:
    """对外展示口径：箱区状态以流转状态为准，保证列表、导出、刷新后看到的一致。"""
    item = dict(row)
    item["箱区状态"] = str(row.get("status") or "")
    return item


def _dedupe_by_code(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按箱区编号去重：同一编号只留第一条，既有堆场排位顺序保持不变。"""
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        code = str(row.get("箱区编号") or "").strip()
        if code:
            if code in seen:
                continue
            seen.add(code)
        unique.append(row)
    return unique


class YardService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = _dedupe_by_code(store.rows(MODULE))
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("箱区编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [_present(row) for row in rows[start:start + size]], total

    def capacity_mismatches(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """单独挑出箱位对不上的箱区：已用箱位 + 可用箱位超过堆放层数。

        取数口径与列表、导出完全一致（同样的筛选与去重），字段读不成数字的记录
        不参与对账，避免样例文本被误判。
        """
        rows, _ = self.list_entries(keyword=keyword, status=status, page=1, size=100000)
        mismatched: list[dict[str, Any]] = []
        for row in rows:
            used = _as_number(row.get("已用箱位"))
            available = _as_number(row.get("可用箱位"))
            layers = _as_number(row.get("堆放层数"))
            if used is None or available is None or layers is None:
                continue
            if used + available > layers:
                item = dict(row)
                item["异常原因"] = (
                    f"已用箱位+可用箱位（{used + available:g}）超过堆放层数（{layers:g}）"
                )
                mismatched.append(item)
        return mismatched

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return _present(row) if row is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        code = str(values.get("箱区编号") or "").strip()
        rows = store.rows(MODULE)
        if any(str(row.get("箱区编号") or "").strip() == code for row in rows):
            return None, f"箱区编号 {code} 已存在，箱区编号重复登记会造成台账重复"
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return _present(entry), None

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"箱区 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于堆场管理可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["箱区状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return _present(entry), f"箱区已{action}"
