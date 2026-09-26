"""箱区台账取数与导出口径测试：去重、封闭箱区、箱位异常、列表/导出一致性。

只依赖标准库（unittest），直接调用 service 与路由函数，无需启动 HTTP 服务。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.routers import yard as yard_router  # noqa: E402
from app.services.yard import CLOSED_STATUS, YardService  # noqa: E402
from app.store import store  # noqa: E402


class YardLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = YardService()
        self.original_rows = [dict(row) for row in store.rows("yard")]

    def tearDown(self) -> None:
        # 动作类测试会改动内存仓库，测完还原，保证用例之间互不影响。
        store.rows("yard").clear()
        store.rows("yard").extend(self.original_rows)

    def test_duplicate_code_keeps_first_only(self) -> None:
        entries = self.service.query_entries()
        codes = [row["箱区编号"] for row in entries]
        self.assertEqual(len(codes), len(set(codes)))
        # YARD-0003 有两条（id 3 与 6），只保留 id 最小的首条。
        match = [row for row in entries if row["箱区编号"] == "YARD-0003"]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0]["id"], 3)

    def test_closed_yard_hidden_by_default(self) -> None:
        entries = self.service.query_entries()
        self.assertFalse(any(row["status"] == CLOSED_STATUS for row in entries))

        shown = self.service.query_entries(include_closed=True)
        self.assertIn("YARD-0004", [row["箱区编号"] for row in shown])

        closed_only = self.service.query_entries(status=CLOSED_STATUS)
        self.assertEqual([row["箱区编号"] for row in closed_only], ["YARD-0004"])

    def test_capacity_mismatch_flagged(self) -> None:
        entries = self.service.query_entries()
        bad = {row["箱区编号"]: row for row in entries if row["箱位异常"]}
        self.assertEqual(set(bad), {"YARD-0005", "YARD-0008"})
        self.assertIn("超过堆放层数", bad["YARD-0005"]["异常说明"])

        good = [row for row in entries if row["箱区编号"] not in {"YARD-0005", "YARD-0008"}]
        self.assertTrue(all(not row["箱位异常"] for row in good))

    def test_list_and_export_share_same_scope(self) -> None:
        for kwargs in (
            {},
            {"keyword": "YARD-000"},
            {"status": "正常堆放"},
            {"include_closed": True},
            {"keyword": "YARD-0008", "include_closed": True},
        ):
            page_items, total, anomalies, summary = self.service.list_entries(
                page=1, size=200, **kwargs
            )
            exported = self.service.query_entries(**kwargs)
            self.assertEqual([r["id"] for r in page_items], [r["id"] for r in exported], kwargs)
            self.assertEqual(total, len(exported), kwargs)
            self.assertEqual(
                [r["id"] for r in anomalies],
                [r["id"] for r in exported if r["箱位异常"]],
                kwargs,
            )
            self.assertEqual(summary, self.service.summarize(exported), kwargs)

    def test_export_endpoint_uses_current_filters(self) -> None:
        payload = yard_router.export_entries(keyword="YARD-0002", status=None, include_closed=False)
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["箱区编号"], "YARD-0002")
        self.assertEqual(
            payload["filters"], {"keyword": "YARD-0002", "status": "", "include_closed": False}
        )

    def test_export_route_registered_before_entry_detail(self) -> None:
        # 回归：/export 必须先于 /{entry_id} 注册，否则会被当成箱区 id 解析。
        paths = [route.path for route in yard_router.router.routes]
        self.assertIn("/api/yard/export", paths)
        self.assertLess(
            paths.index("/api/yard/export"),
            paths.index("/api/yard/{entry_id}"),
        )

    def test_deterministic_order(self) -> None:
        first = [row["id"] for row in self.service.query_entries(include_closed=True)]
        second = [row["id"] for row in self.service.query_entries(include_closed=True)]
        self.assertEqual(first, second)
        self.assertEqual(first, sorted(first))

    def test_close_action_refreshes_list_consistency(self) -> None:
        entry, message = self.service.run_action(1, "封闭箱区")
        self.assertIsNotNone(entry)
        entries = self.service.query_entries()
        # 执行封闭后刷新，该箱区按同一口径从默认列表与导出中消失。
        self.assertNotIn("YARD-0001", [row["箱区编号"] for row in entries])
        with_closed = self.service.query_entries(include_closed=True)
        self.assertIn("YARD-0001", [row["箱区编号"] for row in with_closed])


if __name__ == "__main__":
    unittest.main()
