import json
import tempfile
import unittest
from pathlib import Path

from helena_core import paths


class PathsTests(unittest.TestCase):
    def test_detects_work_v2_root(self):
        root = paths.project_root()

        self.assertEqual(root.name, "work_v2")
        self.assertTrue((root / "helena_core" / "paths.py").exists())

    def test_default_paths_are_relative_to_root(self):
        root = paths.project_root()
        loaded = paths.load_paths()

        self.assertEqual(loaded.root, root)
        self.assertEqual(loaded.config, root / "config")
        self.assertEqual(loaded.scripts, root)
        self.assertEqual(loaded.outputs, root / "outputs")
        self.assertEqual(loaded.logs, root / "logs")
        self.assertEqual(loaded.data, root / "data")
        self.assertEqual(loaded.tests, root / "tests")

    def test_paths_work_when_folders_do_not_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sample_root"
            config_path = root / "config" / "missing.json"
            loaded = paths.load_paths(root=root, config_path=config_path, environ={})

        self.assertEqual(loaded.outputs, root / "outputs")
        self.assertEqual(loaded.logs, root / "logs")
        self.assertEqual(loaded.data, root / "data")

    def test_config_and_environment_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            config_dir = root / "config"
            config_dir.mkdir(parents=True)
            config_path = config_dir / "environment.json"
            config_path.write_text(
                json.dumps({"paths": {"outputs": "custom_outputs", "external": "external_data"}}),
                encoding="utf-8",
            )
            env_outputs = Path(tmp) / "env_outputs"
            loaded = paths.load_paths(
                root=root,
                config_path=config_path,
                environ={"HELENA_OUTPUTS_DIR": str(env_outputs)},
            )

        self.assertEqual(loaded.outputs, env_outputs)
        self.assertEqual(loaded.external, root / "external_data")

    def test_new_modules_do_not_embed_machine_paths(self):
        root = paths.project_root()
        checked = [
            root / "helena_core" / "__init__.py",
            root / "helena_core" / "environment.py",
            root / "helena_core" / "paths.py",
        ]
        forbidden = ("C:" + "\\", "Users" + "\\", "Documents" + "\\", "Codex", "Ser" + "ver")

        for path in checked:
            text = path.read_text(encoding="utf-8")
            for value in forbidden:
                self.assertNotIn(value, text)


if __name__ == "__main__":
    unittest.main()
