import importlib.util
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest


class InstallScriptStartScriptTemplateTests(unittest.TestCase):
    @staticmethod
    def _load_start_script_template() -> str:
        install_script = Path("install.sh").read_text(encoding="utf-8")
        match = re.search(
            r"cat > \"\$INSTALL_DIR/start\.sh\" << 'SCRIPT'\n(.*?)\n^SCRIPT$",
            install_script,
            re.DOTALL | re.MULTILINE,
        )

        if match is None:
            raise AssertionError("install.sh should contain the start.sh template")

        return match.group(1)

    def test_start_script_unsets_electron_run_as_node_before_launch(self) -> None:
        start_script_template = self._load_start_script_template()

        self.assertIn(
            "unset ELECTRON_RUN_AS_NODE",
            start_script_template,
            "start.sh must clear ELECTRON_RUN_AS_NODE so Electron does not boot in Node mode",
        )
        self.assertLess(
            start_script_template.index("unset ELECTRON_RUN_AS_NODE"),
            start_script_template.index('exec "$SCRIPT_DIR/electron"'),
            "ELECTRON_RUN_AS_NODE must be cleared before launching Electron",
        )

    def test_start_script_unsets_ld_preload_before_launch(self) -> None:
        start_script_template = self._load_start_script_template()

        self.assertIn(
            "unset LD_PRELOAD",
            start_script_template,
            "start.sh must clear LD_PRELOAD so shell-level preload hooks cannot crash Electron",
        )
        self.assertLess(
            start_script_template.index("unset LD_PRELOAD"),
            start_script_template.index('exec "$SCRIPT_DIR/electron"'),
            "LD_PRELOAD must be cleared before launching Electron",
        )

    def test_install_script_applies_committed_patch_bundle(self) -> None:
        install_script = Path("install.sh").read_text(encoding="utf-8")

        self.assertIn(
            'python3 "$SCRIPT_DIR/scripts/apply_patch_bundle.py"',
            install_script,
            "install.sh should reuse the committed patch bundle helper",
        )
        self.assertIn(
            '--bundle-dir "$SCRIPT_DIR/patches/codex-desktop"',
            install_script,
            "install.sh should point at the committed Linux patch bundle",
        )
        self.assertIn(
            '--asar "$INSTALL_DIR/resources/app.asar"',
            install_script,
            "install.sh should patch the installed app.asar for unpackaged runs",
        )
        self.assertIn(
            '--target-dir "$INSTALL_DIR/content"',
            install_script,
            "install.sh should patch extracted webview assets for unpackaged runs",
        )

    def test_linux_picker_patch_does_not_shadow_path_module(self) -> None:
        manifest = json.loads(Path("patches/codex-desktop/manifest.json").read_text(encoding="utf-8"))
        rule = next(
            replacement
            for replacement in manifest["replacements"]
            if replacement["name"] == "linux-picker-resolve-parent-directory"
        )

        spec = importlib.util.spec_from_file_location(
            "apply_patch_bundle",
            Path("scripts/apply_patch_bundle.py"),
        )
        if spec is None or spec.loader is None:
            raise AssertionError("Failed to load apply_patch_bundle.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        original = (
            "async resolveWorkspaceRoot(e){try{const t=L(e,this.host);"
            "return(await(0,p.stat)(t)).isDirectory()?(0,i.resolve)(t):null}"
            "catch(e){return J().warning(`Failed to stat workspace root`,"
            "{safe:{},sensitive:{error:e}}),null}}"
        )

        with TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / ".vite" / "build" / "main-test.js"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(original, encoding="utf-8")
            module.apply_rule(rule, Path(temp_dir))
            patched = file_path.read_text(encoding="utf-8")

        self.assertIn("__codexStat", patched)
        self.assertIn("__codexParentDir", patched)
        self.assertIn("(0,i.resolve)", patched)

    def test_linux_picker_patch_self_heals_buggy_bundle(self) -> None:
        manifest = json.loads(Path("patches/codex-desktop/manifest.json").read_text(encoding="utf-8"))
        rule = next(
            replacement
            for replacement in manifest["replacements"]
            if replacement["name"] == "linux-picker-resolve-parent-directory-self-heal"
        )

        spec = importlib.util.spec_from_file_location(
            "apply_patch_bundle",
            Path("scripts/apply_patch_bundle.py"),
        )
        if spec is None or spec.loader is None:
            raise AssertionError("Failed to load apply_patch_bundle.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        buggy = (
            "async resolveWorkspaceRoot(e){try{let t=L(e,this.host),i=await(0,p.stat)(t);"
            "if(i.isDirectory())return(0,i.resolve)(t);if(i.isFile()){let n=(0,i.dirname)(t),"
            "o=await(0,p.stat)(n);if(o.isDirectory())return(0,i.resolve)(n)}return null}"
            "catch(e){return J().warning(`Failed to stat workspace root`,"
            "{safe:{},sensitive:{error:e}}),null}}"
        )

        with TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / ".vite" / "build" / "main-test.js"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(buggy, encoding="utf-8")
            module.apply_rule(rule, Path(temp_dir))
            patched = file_path.read_text(encoding="utf-8")

        self.assertIn("__codexStat", patched)
        self.assertIn("__codexParentDir", patched)
        self.assertIn("(0,i.resolve)", patched)


if __name__ == "__main__":
    unittest.main()
