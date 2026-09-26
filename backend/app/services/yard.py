"""堆场管理（箱区台账）业务规则：筛选口径、去重、箱位校验与状态流转都收在这里。

列表查询与导出共用 :meth:`YardService.query_entries` 这一条取数链路，保证任何机器、
任何时刻「页面看到的」和「导出拿到的」完全一致：

1. 按 id 稳定排序，结果不随机器、进程或字典顺序变化；
2. 封闭箱区默认不参与取数，除非显式要求包含或按「已封闭」状态筛选；
3. 同一箱区编号只保留 id 最小的一条（首条为准），重复编号不重复出现；
4. 逐条核对「已用箱位 + 可用箱位」与堆放层数（容量上限），对不上的记录打上异常标记
   并写入异常说明，供列表高亮与导出单独成段。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "yard"
REQUIRED_FIELDS = ["箱区编号", "箱区名称", "堆放层数"]
STATUS_ORDER = ["待启用", "正常堆放", "接近满载", "已封闭"]
CLOSED_STATUS = "已封闭"
ACTION_RULES = {"启用箱区": "正常堆放", "封闭箱区": "已封闭", "腾空箱区": "待启用"}
NEGATIVE_ACTIONS = []


def _to_int(value: Any) -> int | None:
    """把字段值转成非负整数；空值或非数字（例如占位文本）一律返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = int(float(text))
    except ValueError:
        return None
    return number if number >= 0 else None


def _annotate(row: dict[str, Any]) -> dict[str, Any]:
    """复制一条箱区并补齐展示字段、箱位校验结果；只读，不回写数据仓库。"""
    entry = dict(row)
    status = str(entry.get("status") or "").strip()
    entry["箱区状态"] = status

    layers = _to_int(entry.get("堆放层数"))
    used = _to_int(entry.get("已用箱位"))
    available = _to_int(entry.get("可用箱位"))

    reasons: list[str] = []
    if layers is None:
        reasons.append("堆放层数不是有效数字")
    if used is None:
        reasons.append("已用箱位不是有效数字")
    if available is None:
        reasons.append("可用箱位不是有效数字")

    occupied: int | None = None
    if used is not None and available is not None:
        occupied = used + available
        if layers is not None and occupied != layers:
            relation = "超过" if occupied > layers else "不足"
            reasons.append(
                f"已用箱位+可用箱位={occupied}，{relation}堆放层数（容量上限）{layers}"
            )

    entry["箱位异常"] = bool(reasons)
    entry["异常说明"] = "；".join(reasons)
    return entry


class YardService:
    def query_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        include_closed: bool = False,
    ) -> list[dict[str, Any]]:
        """按当前条件取数并完成去重、补字段、箱位校验；列表和导出共用这一份口径。"""
        rows = sorted(store.rows(MODULE), key=lambda row: int(row.get("id", 0)))

        keyword = (keyword or "").strip()
        status = (status or "").strip()
        # 显式查「已封闭」时，即使没有勾选包含封闭箱区也应当能查出来。
        if status == CLOSED_STATUS:
            include_closed = True

        if keyword:
            rows = [row for row in rows if keyword in str(row.get("箱区编号", ""))]
        if status:
            rows = [row for row in rows if str(row.get("status") or "").strip() == status]
        if not include_closed:
            rows = [row for row in rows if str(row.get("status") or "").strip() != CLOSED_STATUS]

        # 同一箱区编号只保留首条（id 最小），后续重复记录不进入列表与导出。
        seen: set[str] = set()
        unique_rows: list[dict[str, Any]] = []
        for row in rows:
            code = str(row.get("箱区编号") or "").strip()
            if code in seen:
                continue
            seen.add(code)
            unique_rows.append(row)

        return [_annotate(row) for row in unique_rows]

    def summarize(self, entries: list[dict[str, Any]]) -> dict[str, int]:
        """对同一份取数结果做汇总，保证卡片数字与列表、导出对得上。"""
        active = [
            row for row in entries
            if str(row.get("status") or "").strip() != CLOSED_STATUS
        ]
        near_full = sum(1 for row in entries if str(row.get("status") or "").strip() == "接近满载")
        available_total = sum(
            value for value in (_to_int(row.get("可用箱位")) for row in entries)
            if value is not None
        )
        return {
            "在用箱区": len(active),
            "接近满载箱区": near_full,
            "可用箱位总数": available_total,
            "箱位异常数": sum(1 for row in entries if row.get("箱位异常")),
        }

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        include_closed: bool = False,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int, list[dict[str, Any]], dict[str, int]]:
        """分页返回当前条件下的箱区，同时给出异常清单与汇总；统计基于全量结果而非当前页。"""
        entries = self.query_entries(keyword=keyword, status=status, include_closed=include_closed)
        anomalies = [row for row in entries if row.get("箱位异常")]
        summary = self.summarize(entries)
        total = len(entries)
        start = max(page - 1, 0) * size
        return entries[start:start + size], total, anomalies, summary

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return _annotate(row) if row is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return _annotate(entry), []

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
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return _annotate(entry), f"箱区已{action}"
