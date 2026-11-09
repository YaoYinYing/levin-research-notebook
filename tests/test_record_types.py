"""The report spine is fixed; the middle sections follow record_type."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "mcp" / "runner"))
from notebook import Notebook  # noqa: E402

# Artifact root is overridable so the suite runs on any machine; the default is a
# process-local temp directory, never a hard-coded home path.
SCRATCH = Path(os.environ.get("NOTEBOOK_TEST_SCRATCH")
               or Path(tempfile.gettempdir()) / "levin-research-notebook-tests" / "type-tests")


def sections(markdown_text):
    return [line[3:].strip() for line in markdown_text.splitlines() if line.startswith("## ")]


class RecordTypeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        cls.session = Path(tempfile.mkdtemp(prefix="types-", dir=SCRATCH))

    def build(self, kind, **finalize_kwargs):
        workspace = Path(tempfile.mkdtemp(prefix=kind + "-", dir=self.session))
        (workspace / "data").mkdir()
        (workspace / "data" / "in.csv").write_text("a\n1\n")
        notebook = Notebook(str(workspace))
        eid = notebook.init(task_id=f"t-{kind}", agent_id="a", title=f"{kind} record",
                            objective="Compare section templates.", purpose="Because templates differ.",
                            record_type=kind)["experiment_id"]
        artifact = notebook.register_artifact(eid, {"role": "raw", "location": "data/in.csv", "description": "in"})
        notebook.checkpoint(eid, "a", "method", "Procedure text.", title="Main")
        notebook.checkpoint(eid, "a", "conclusion", "Supported here.", title="C1",
                            evidence_ids=[artifact["artifact_id"]])
        result = notebook.finalize(eid, "success", "Supported.", "Limited.",
                                   {"beneficial": False, "reason": "none", "figure_ids": [], "reviewed_by": "a"},
                                   request_id="once", **finalize_kwargs)
        return (workspace / result["report"]["source_path"]).read_text(), result

    def test_experiment_template_matches_the_agreed_outline(self):
        text, _ = self.build("experiment")
        self.assertEqual(sections(text)[:9], [
            "1. 实验目的", "2. 实验策略", "3. 实验方法和计划", "4. 实验材料", "5. 实验结果",
            "6. 实验结论和不足", "7. 下一步计划", "8. 经验教训", "9. 数据空间统计"])

    def test_analysis_template_replaces_experiment_wording(self):
        text, _ = self.build("analysis")
        joined = " ".join(sections(text))
        self.assertIn("分析策略", joined)
        self.assertNotIn("实验策略", joined)
        self.assertIn("数据与工具", joined)

    def test_literature_template_has_search_references_and_citations(self):
        text, _ = self.build("literature_review",
                             search_strategy={"databases": "PubMed", "query": "MM-PBSA"},
                             references=[{"id": "R1", "citation": "Doe 2024", "key_findings": "positive"}],
                             citations=[{"from": "R1", "to": "R1", "relation": "self"}],
                             synthesis="Mixed evidence.")
        joined = " ".join(sections(text))
        for expected in ("研究问题与范围", "检索策略", "文献清单", "证据综合", "复算与核验", "引用关系"):
            self.assertIn(expected, joined)
        self.assertIn("[1]. ", text)
        self.assertIn("年份未记录", text)
        self.assertIn("```mermaid", text)
        self.assertNotIn("实验材料", joined)

    def test_shared_spine_is_present_in_every_type(self):
        for kind in ("experiment", "analysis", "literature_review"):
            text, _ = self.build(kind)
            joined = " ".join(sections(text))
            for spine in ("结论", "不足", "下一步计划", "经验教训", "数据空间统计"):
                self.assertIn(spine, joined, f"{kind} missing {spine}")

    def test_extra_sections_are_appended_not_substituted(self):
        text, _ = self.build("analysis", extra_sections=[{"title": "Relation to exp-x", "text": "Explains it."}])
        joined = " ".join(sections(text))
        self.assertIn("补充说明", joined)
        self.assertIn("Relation to exp-x", text)
        self.assertIn("结论与不足", joined)

    def test_reference_links_surface_in_artifacts_and_runs(self):
        workspace = Path(tempfile.mkdtemp(prefix="refs-", dir=self.session))
        (workspace / "data").mkdir()
        (workspace / "data" / "s.pdb").write_text("END\n")
        notebook = Notebook(str(workspace))
        eid = notebook.init(task_id="t-refs", agent_id="a", title="refs", objective="link check",
                            record_type="literature_review")["experiment_id"]
        notebook.register_run(eid, {"backend": "local", "host": "mac", "execution_status": "success",
                                    "command": "python fetch.py", "environment": {"python": "3.11"},
                                    "reference_id": "R1"})
        notebook.register_artifact(eid, {"role": "raw", "location": "data/s.pdb", "description": "pulled structure",
                                         "reference_id": "R1"})
        notebook.checkpoint(eid, "a", "method", "Refetch and re-minimise.", title="Verify")
        result = notebook.finalize(eid, "success", "ok", "narrow",
                                   {"beneficial": False, "reason": "none", "figure_ids": [], "reviewed_by": "a"},
                                   references=[{"id": "R1", "citation": "Doe 2024"}], request_id="r1")
        text = (workspace / result["report"]["source_path"]).read_text()
        self.assertIn("对应文献 `R1`", text)
        self.assertIn("文献 R1", text)

    def test_unknown_record_type_is_rejected(self):
        workspace = Path(tempfile.mkdtemp(prefix="bad-", dir=self.session))
        with self.assertRaises(Exception):
            Notebook(str(workspace)).init(task_id="t", agent_id="a", title="x", objective="y",
                                          record_type="blog")


if __name__ == "__main__":
    unittest.main(verbosity=2)
