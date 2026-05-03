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

    @staticmethod
    def _load_patch_rule(name: str) -> dict:
        manifest = json.loads(
            Path("patches/codex-desktop/manifest.json").read_text(encoding="utf-8")
        )
        return next(
            replacement for replacement in manifest["replacements"] if replacement["name"] == name
        )

    @staticmethod
    def _load_apply_patch_bundle_module():
        spec = importlib.util.spec_from_file_location(
            "apply_patch_bundle",
            Path("scripts/apply_patch_bundle.py"),
        )
        if spec is None or spec.loader is None:
            raise AssertionError("Failed to load apply_patch_bundle.py")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

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

    def test_start_script_waits_for_webview_server_before_launch(self) -> None:
        start_script_template = self._load_start_script_template()

        self.assertIn("wait_for_webview_server()", start_script_template)
        self.assertIn("if ! wait_for_webview_server; then", start_script_template)
        self.assertLess(
            start_script_template.index("if ! wait_for_webview_server; then"),
            start_script_template.index('exec "$SCRIPT_DIR/electron"'),
            "webview readiness must be checked before launching Electron",
        )

    def test_start_script_verifies_webview_origin_before_launch(self) -> None:
        start_script_template = self._load_start_script_template()

        self.assertIn("verify_webview_origin()", start_script_template)
        self.assertIn(
            'if ! verify_webview_origin "http://127.0.0.1:5175/index.html" "$WEBVIEW_DIR/index.html"; then',
            start_script_template,
        )
        self.assertIn('local expected_file="$2"', start_script_template)
        self.assertIn("expected = expected_file.read_bytes()", start_script_template)
        self.assertIn("if body != expected:", start_script_template)
        self.assertLess(
            start_script_template.index(
                'if ! verify_webview_origin "http://127.0.0.1:5175/index.html" "$WEBVIEW_DIR/index.html"; then'
            ),
            start_script_template.index('exec "$SCRIPT_DIR/electron"'),
            "webview origin must be validated before launching Electron",
        )

    def test_start_script_searches_common_cli_locations(self) -> None:
        start_script_template = self._load_start_script_template()

        self.assertIn("find_codex_cli()", start_script_template)
        self.assertIn("$HOME/.local/bin/codex", start_script_template)
        self.assertIn("$HOME/.local/share/pnpm/codex", start_script_template)
        self.assertIn('${NVM_DIR:-$HOME/.nvm}/nvm.sh', start_script_template)

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
        rule = self._load_patch_rule("linux-picker-resolve-parent-directory")
        module = self._load_apply_patch_bundle_module()

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
        rule = self._load_patch_rule("linux-picker-resolve-parent-directory-self-heal")
        module = self._load_apply_patch_bundle_module()

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

    def test_linux_file_manager_patch_adds_linux_target(self) -> None:
        rule = self._load_patch_rule("linux-file-manager-handler")
        module = self._load_apply_patch_bundle_module()

        original = (
            "var ka=$i({id:`fileManager`,label:`Finder`,icon:`apps/finder.png`,kind:`fileManager`,"
            "darwin:{detect:()=>`open`,args:e=>Ti(e)},win32:{label:`File Explorer`,"
            "icon:`apps/file-explorer.png`,detect:Aa,args:e=>Ti(e),open:async({path:e})=>ja(e)}});"
        )

        with TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / ".vite" / "build" / "main-test.js"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(original, encoding="utf-8")
            module.apply_rule(rule, Path(temp_dir))
            patched = file_path.read_text(encoding="utf-8")

        self.assertIn("linux:{label:`File Manager`", patched)
        self.assertIn("detect:()=>`linux-file-manager`", patched)
        self.assertIn("open:async({path:e})=>ja(e)", patched)

    def test_linux_file_manager_patch_matches_alternate_minified_helper_names(self) -> None:
        rule = self._load_patch_rule("linux-file-manager-handler")
        module = self._load_apply_patch_bundle_module()

        original = (
            "var sa=$i({id:`fileManager`,label:`Finder`,icon:`apps/finder.png`,kind:`fileManager`,"
            "darwin:{detect:()=>`open`,args:e=>ai(e)},win32:{label:`File Explorer`,"
            "icon:`apps/file-explorer.png`,detect:ca,args:e=>ai(e),open:async({path:e})=>la(e)}});"
        )

        with TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / ".vite" / "build" / "main-test.js"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(original, encoding="utf-8")
            module.apply_rule(rule, Path(temp_dir))
            patched = file_path.read_text(encoding="utf-8")

        self.assertIn("darwin:{detect:()=>`open`,args:e=>ai(e)}", patched)
        self.assertIn("win32:{label:`File Explorer`,icon:`apps/file-explorer.png`,detect:ca,args:e=>ai(e)", patched)
        self.assertIn("linux:{label:`File Manager`", patched)
        self.assertIn("open:async({path:e})=>la(e)", patched)

    def test_linux_file_manager_patch_matches_latest_bundle_constructor_helper(self) -> None:
        rule = self._load_patch_rule("linux-file-manager-handler")
        module = self._load_apply_patch_bundle_module()

        original = (
            "var lu=jl({id:`fileManager`,label:`Finder`,icon:`apps/finder.png`,kind:`fileManager`,"
            "darwin:{detect:()=>`open`,args:e=>il(e)},win32:{label:`File Explorer`,"
            "icon:`apps/file-explorer.png`,detect:uu,args:e=>il(e),open:async({path:e})=>du(e)}});"
        )

        with TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / ".vite" / "build" / "main-test.js"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(original, encoding="utf-8")
            module.apply_rule(rule, Path(temp_dir))
            patched = file_path.read_text(encoding="utf-8")

        self.assertIn("var lu=jl(", patched)
        self.assertIn("darwin:{detect:()=>`open`,args:e=>il(e)}", patched)
        self.assertIn("win32:{label:`File Explorer`,icon:`apps/file-explorer.png`,detect:uu,args:e=>il(e)", patched)
        self.assertIn("linux:{label:`File Manager`", patched)
        self.assertIn("open:async({path:e})=>du(e)", patched)

    def test_linux_file_manager_patch_matches_dollar_prefixed_minified_names(self) -> None:
        rule = self._load_patch_rule("linux-file-manager-handler")
        module = self._load_apply_patch_bundle_module()

        original = (
            "var $u=j$({id:`fileManager`,label:`Finder`,icon:`apps/finder.png`,kind:`fileManager`,"
            "darwin:{detect:()=>`open`,args:$e=>$l($e)},win32:{label:`File Explorer`,"
            "icon:`apps/file-explorer.png`,detect:$d,args:$e=>$l($e),open:async({path:$e})=>$o($e)}});"
        )

        with TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / ".vite" / "build" / "main-test.js"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(original, encoding="utf-8")
            module.apply_rule(rule, Path(temp_dir))
            patched = file_path.read_text(encoding="utf-8")

        self.assertIn("var $u=j$(", patched)
        self.assertIn("darwin:{detect:()=>`open`,args:$e=>$l($e)}", patched)
        self.assertIn("detect:$d,args:$e=>$l($e)", patched)
        self.assertIn("linux:{label:`File Manager`", patched)
        self.assertIn("open:async({path:$e})=>$o($e)", patched)

    def test_linux_file_manager_patch_matches_assignment_without_var(self) -> None:
        rule = self._load_patch_rule("linux-file-manager-handler")
        module = self._load_apply_patch_bundle_module()

        original = (
            "Ih=rh({id:`fileManager`,label:`Finder`,icon:`apps/finder.png`,kind:`fileManager`,"
            "darwin:{detect:()=>`open`,args:e=>km(e)},win32:{label:`File Explorer`,"
            "icon:`apps/file-explorer.png`,detect:Lh,args:e=>km(e),open:async({path:e})=>Rh(e)}});"
        )

        with TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / ".vite" / "build" / "main-test.js"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(original, encoding="utf-8")
            module.apply_rule(rule, Path(temp_dir))
            patched = file_path.read_text(encoding="utf-8")

        self.assertIn("Ih=rh(", patched)
        self.assertIn("darwin:{detect:()=>`open`,args:e=>km(e)}", patched)
        self.assertIn("detect:Lh,args:e=>km(e)", patched)
        self.assertIn("linux:{label:`File Manager`", patched)
        self.assertIn("open:async({path:e})=>Rh(e)", patched)

    def test_linux_window_menu_rules_apply(self) -> None:
        auto_hide_rule = self._load_patch_rule("linux-window-auto-hide-menu")
        hide_menu_rule = self._load_patch_rule("linux-window-hide-menu-bar")
        module = self._load_apply_patch_bundle_module()

        original = (
            "new t.BrowserWindow({width:y,height:b,...process.platform===`win32`?{autoHideMenuBar:!0}:{},"
            "...E==null?{}:{backgroundMaterial:E}});process.platform===`win32`&&D.removeMenu(),"
        )

        with TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / ".vite" / "build" / "main-test.js"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(original, encoding="utf-8")
            module.apply_rule(auto_hide_rule, Path(temp_dir))
            module.apply_rule(hide_menu_rule, Path(temp_dir))
            patched = file_path.read_text(encoding="utf-8")

        self.assertIn(
            "process.platform===`win32`||process.platform===`linux`?{autoHideMenuBar:!0}:{}",
            patched,
        )
        self.assertIn("process.platform===`linux`&&D.setMenuBarVisibility(!1),", patched)

    def test_linux_window_hide_menu_rule_matches_latest_bundle_variable_names(self) -> None:
        rule = self._load_patch_rule("linux-window-hide-menu-bar")
        module = self._load_apply_patch_bundle_module()

        original = "process.platform===`win32`&&k.removeMenu(),"

        with TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / ".vite" / "build" / "main-test.js"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(original, encoding="utf-8")
            module.apply_rule(rule, Path(temp_dir))
            patched = file_path.read_text(encoding="utf-8")

        self.assertIn("process.platform===`linux`&&k.setMenuBarVisibility(!1),", patched)
        self.assertIn("process.platform===`win32`&&k.removeMenu(),", patched)

    def test_linux_avatar_overlay_defaults_to_pointer_interactive(self) -> None:
        rule = self._load_patch_rule("linux-avatar-overlay-default-pointer-interactive")
        module = self._load_apply_patch_bundle_module()

        original = (
            "this.rendererReady=this.windowManager.isWebContentsReady(n.webContents.id),"
            "this.pointerInteractive=!1,this.mousePassthroughEnabled=!1,"
            "process.platform===`darwin`?n.setVisibleOnAllWorkspaces(!0,{visibleOnFullScreen:!0,"
            "skipTransformProcessType:!0}):n.setVisibleOnAllWorkspaces(!0),"
        )

        with TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / ".vite" / "build" / "main-test.js"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(original, encoding="utf-8")
            module.apply_rule(rule, Path(temp_dir))
            patched = file_path.read_text(encoding="utf-8")

        self.assertIn(
            "this.pointerInteractive=process.platform===`linux`",
            patched,
        )
        self.assertIn("this.mousePassthroughEnabled=!1", patched)

    def test_linux_file_manager_file_open_uses_parent_directory_on_linux(self) -> None:
        rule = self._load_patch_rule("linux-file-manager-open-file-parent-directory")
        module = self._load_apply_patch_bundle_module()

        original = (
            "async function ja(e){let n=Ma(e);if(n&&(0,a.statSync)(n).isFile()){"
            "t.shell.showItemInFolder(n);return}let r=n??e,i=await t.shell.openPath(r);if(i)throw Error(i)}"
        )

        with TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / ".vite" / "build" / "main-test.js"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(original, encoding="utf-8")
            module.apply_rule(rule, Path(temp_dir))
            patched = file_path.read_text(encoding="utf-8")

        self.assertIn("if(process.platform===`linux`)", patched)
        self.assertIn("lastIndexOf(`/`)", patched)
        self.assertIn("await t.shell.openPath(__codexParentDir)", patched)
        self.assertIn("t.shell.showItemInFolder(n);return", patched)

    def test_linux_file_manager_file_open_matches_latest_bundle_names(self) -> None:
        rule = self._load_patch_rule("linux-file-manager-open-file-parent-directory")
        module = self._load_apply_patch_bundle_module()

        original = (
            "async function du(e){let t=fu(e);if(t&&(0,o.statSync)(t).isFile()){"
            "n.shell.showItemInFolder(t);return}let r=t??e,i=await n.shell.openPath(r);if(i)throw Error(i)}"
        )

        with TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / ".vite" / "build" / "main-test.js"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(original, encoding="utf-8")
            module.apply_rule(rule, Path(temp_dir))
            patched = file_path.read_text(encoding="utf-8")

        self.assertIn("if(process.platform===`linux`)", patched)
        self.assertIn("__codexParentDirIndex", patched)
        self.assertIn("await n.shell.openPath(__codexParentDir)", patched)
        self.assertIn("n.shell.showItemInFolder(t);return", patched)

    def test_linux_file_manager_file_open_matches_dollar_prefixed_names(self) -> None:
        rule = self._load_patch_rule("linux-file-manager-open-file-parent-directory")
        module = self._load_apply_patch_bundle_module()

        original = (
            "async function $o($e){let $t=$f($e);if($t&&(0,$s.statSync)($t).isFile()){"
            "$n.shell.showItemInFolder($t);return}let $r=$t??$e,$i=await $n.shell.openPath($r);if($i)throw Error($i)}"
        )

        with TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / ".vite" / "build" / "main-test.js"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(original, encoding="utf-8")
            module.apply_rule(rule, Path(temp_dir))
            patched = file_path.read_text(encoding="utf-8")

        self.assertIn("if(process.platform===`linux`)", patched)
        self.assertIn("__codexParentDirIndex", patched)
        self.assertIn("await $n.shell.openPath(__codexParentDir)", patched)
        self.assertIn("$n.shell.showItemInFolder($t);return", patched)

    def test_linux_opaque_windows_default_patch_applies_to_code_theme_bundle(self) -> None:
        rule = self._load_patch_rule("linux-opaque-windows-default-code-theme")
        module = self._load_apply_patch_bundle_module()

        original = (
            "function x(){return{opaqueWindows:e?.opaqueWindows??n.opaqueWindows,semanticColors:r}}"
        )

        with TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "webview" / "assets" / "code-theme-test.js"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(original, encoding="utf-8")
            module.apply_rule(rule, Path(temp_dir))
            patched = file_path.read_text(encoding="utf-8")

        self.assertIn("navigator.userAgentData?.platform??navigator.platform??navigator.userAgent", patched)
        self.assertIn(".toLowerCase().includes(`linux`)", patched)


if __name__ == "__main__":
    unittest.main()
