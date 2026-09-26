"""堆场管理（箱区台账）接口：维护箱区，覆盖启用、封闭、腾空等动作，并按当前条件取数导出。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.yard import CLOSED_STATUS, STATUS_ORDER, YardService

router = APIRouter(prefix="/api/yard", tags=["堆场管理"])

service = YardService()

LIST_FIELDS = ["箱区编号", "箱区名称", "堆放层数", "可用箱位", "已用箱位", "所属堆场", "责任人", "箱区状态"]
STATUSES = ["待启用", "正常堆放", "接近满载", "已封闭"]


def _check_status(status: str | None) -> None:
    if status and status not in STATUS_ORDER:
        raise HTTPException(
            status_code=400,
            detail=f"箱区状态仅支持：{'、'.join(STATUS_ORDER)}",
        )


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按箱区编号检索"),
    status: str | None = Query(default=None, description="待启用、正常堆放、接近满载、已封闭"),
    include_closed: bool = Query(default=False, description="是否包含已封闭箱区"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按箱区编号与状态过滤箱区台账；封闭箱区默认隐藏，结果去重并标注箱位异常。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    _check_status(status)
    items, total, anomalies, summary = service.list_entries(
        keyword=keyword,
        status=status,
        include_closed=include_closed,
        page=page,
        size=size,
    )
    return PageResult(
        items=items,
        total=total,
        page=page,
        size=size,
        anomalies=anomalies,
        summary=summary,
    )


# 注意：导出路由必须放在 /{entry_id} 之前，否则 "export" 会被当成箱区 id 解析并报 422。
@router.get("/export")
def export_entries(
    keyword: str | None = Query(default=None, description="按箱区编号检索，与列表一致"),
    status: str | None = Query(default=None, description="待启用、正常堆放、接近满载、已封闭"),
    include_closed: bool = Query(default=False, description="是否包含已封闭箱区"),
) -> dict[str, Any]:
    """按当前筛选条件导出：与列表共用同一取数口径，重复箱区只留一条，异常记录单独成段。"""
    _check_status(status)
    entries = service.query_entries(keyword=keyword, status=status, include_closed=include_closed)
    anomalies = [row for row in entries if row.get("箱位异常")]
    summary = service.summarize(entries)
    return {
        "module": "yard",
        "total": len(entries),
        "items": entries,
        "anomalies": anomalies,
        "summary": summary,
        "filters": {"keyword": keyword or "", "status": status or "", "include_closed": include_closed},
    }


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条箱区明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"箱区 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条箱区，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="箱区已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条箱区执行启用箱区、封闭箱区、腾空箱区；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
