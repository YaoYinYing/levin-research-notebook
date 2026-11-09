"""Guard: every authoring field the library accepts must be reachable through the MCP schema."""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / ".levin-plugin" / "vendor" / "python"))


def _spec():
    spec = importlib.util.spec_from_file_location("plugin_spec_under_test", ROOT / "mcp" / "runner" / "plugin_spec.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.plugin


class SchemaSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tools = {tool.name: tool for tool in _spec().tools}

    def props(self, tool, nested=None):
        schema = self.tools[tool].input_schema
        if nested:
            schema = schema["properties"][nested]
        return set(schema.get("properties", {}))

    def test_init_exposes_expected_result(self):
        self.assertIn("expected_result", self.props("research_record_init"))

    def test_checkpoint_exposes_structured_section_fields(self):
        for field in ("title", "replica", "retry", "when_note", "refers_to"):
            self.assertIn(field, self.props("research_record_checkpoint"))

    def test_finalize_exposes_lessons_and_plans(self):
        for field in ("lessons", "plans"):
            self.assertIn(field, self.props("research_record_finalize"))

    def test_register_run_exposes_host(self):
        self.assertIn("host", self.props("research_record_register_run", nested="run"))

    def test_init_exposes_outline_authoring_fields(self):
        for field in ("purpose", "implementer", "environment_location"):
            self.assertIn(field, self.props("research_record_init"))

    def test_checkpoint_exposes_supersedes(self):
        self.assertIn("supersedes", self.props("research_record_checkpoint"))

    def test_finalize_exposes_outline_sections(self):
        for field in ("strategy", "method_plan", "materials", "results", "footnotes", "remote_space"):
            self.assertIn(field, self.props("research_record_finalize"))

    def test_finalize_exposes_bibtex_inputs(self):
        for field in ("bibtex_path", "bibtex"):
            self.assertIn(field, self.props("research_record_finalize"))

    def test_register_artifact_exposes_remote_provenance(self):
        for field in ("source_origin", "remote_host", "remote_path", "remote_copy_permission"):
            self.assertIn(field, self.props("research_record_register_artifact", nested="artifact"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
