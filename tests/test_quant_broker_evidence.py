from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from quantagent.broker_gateway import BrokerGatewaySpec, build_broker_gateway_snapshot
from quantagent.cli import main
from quantagent.quant_broker_evidence import import_broker_evidence


class QuantBrokerEvidenceImportTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="mako broker evidence ")

    def write_broker_exports(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        (root / "成交记录.csv").write_text(
            "成交日期,成交时间,证券代码,成交价格,成交数量,买卖标志,合同编号,成交编号\n"
            "20260525,09:31:00,000001,10.10,500,买入,ord1,trd1\n",
            encoding="utf-8",
        )
        (root / "委托记录.csv").write_text(
            "委托日期,委托时间,证券代码,委托编号,委托价格,委托数量,成交数量,委托状态,买卖\n"
            "20260525,09:30:59,000001,ord1,10.10,500,500,全部成交,买入\n",
            encoding="utf-8",
        )
        (root / "资金持仓.csv").write_text(
            "券商,资金账号,总资产,可用资金,冻结资金,币种\n"
            "测试证券,123456789,100000,94950,0,CNY\n",
            encoding="utf-8",
        )
        (root / "持仓.csv").write_text(
            "证券代码,持仓数量,可用数量,成本价,浮动盈亏\n"
            "000001,500,500,10.10,0\n",
            encoding="utf-8",
        )
        (root / "交割单.xls").write_text(
            "<table><tr><th>成交日期</th><th>成交时间</th><th>证券代码</th><th>成交价格</th><th>成交数量</th><th>买卖标志</th><th>合同编号</th></tr>"
            "<tr><td>20260526</td><td>09:32:00</td><td>000002</td><td>8.20</td><td>100</td><td>卖出</td><td>ord2</td></tr></table>",
            encoding="gb18030",
        )

    def test_imports_chinese_broker_exports_into_normalized_evidence(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            exports = project / "券商导出"
            self.write_broker_exports(exports)

            result = import_broker_evidence(project, [exports], source="测试证券PC导出", broker_name="测试证券")

            self.assertTrue(result.ok, result.to_dict())
            self.assertIn("fill", result.files)
            self.assertIn("order", result.files)
            self.assertIn("account", result.files)
            self.assertIn("position", result.files)
            self.assertIn("broker", result.files)
            self.assertEqual(result.counts["fill"], 2)
            account_text = Path(result.files["account"]).read_text(encoding="utf-8")
            self.assertIn("acct_sha256_", account_text)
            self.assertNotIn("123456789", account_text)

            snapshot = build_broker_gateway_snapshot(
                project,
                BrokerGatewaySpec(
                    broker_path=result.files["broker"],
                    fill_path=result.files["fill"],
                    order_path=result.files["order"],
                    position_path=result.files["position"],
                    account_path=result.files["account"],
                    source="测试证券PC导出",
                ),
            )

            self.assertTrue(snapshot.has_live_fill_evidence, snapshot.to_dict())
            self.assertTrue(snapshot.has_broker_provenance, snapshot.to_dict())
            self.assertEqual(len(snapshot.fills), 2)

    def test_broker_import_cli_json(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            exports = project / "券商导出"
            self.write_broker_exports(exports)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(
                    [
                        "--no-trust-prompt",
                        "quant",
                        "--project",
                        tmp,
                        "broker-import",
                        str(exports),
                        "--source",
                        "测试证券PC导出",
                        "--broker-name",
                        "测试证券",
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

            self.assertEqual(rc, 0)
            self.assertTrue(payload["ok"])
            self.assertIn("--fill", payload["execution_args"])
            self.assertIn("broker", payload["files"])


if __name__ == "__main__":
    unittest.main()
