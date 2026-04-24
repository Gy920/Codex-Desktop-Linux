# Codex Desktop Patch Bundle

This directory holds the durable assets for the local Linux customizations:

- bundled UI and mono fonts
- CSS overrides that prefer the bundled fonts
- a manifest describing text replacements inside the extracted `app.asar`

The execution helper that applies this bundle to a concrete `app.asar` is kept
out of git on purpose. That keeps repo history clean while still letting local
machines reapply the same patch set after an app update.

What this bundle changes:

- prefers bundled `Ubuntu` and `Ubuntu Mono` fonts over Linux fallback fonts
- keeps the Linux "Select project" flow using directory selection first, then
  falls back to file selection only when the picker fails to return a folder
- resolves a selected file back to its parent directory
- disables the packaged Sparkle / install-update path inside the Electron main
  bundle so prod update prompts do not hard-block the patched Linux build
- overrides selected Statsig gates in the renderer to keep hotkey-window
  available while forcing the app-sunset gate off
- injects a fixed set of desktop feature defaults into both main-thread startup
  and renderer feature overrides, including `artifact`, `artifactsPane`,
  `browserPane`, `ambientSuggestions`, `avatarOverlay`, `multiwindow`,
  `projectlessThreads`, `general_analytics`, `js_repl`, `multi_agent_v2`,
  `realtime_conversation`, `tool_search`, `undo`, and `fast_mode`
- removes the `git clone --sparse` flag from recommended-skills bootstrap

Expected local workflow after updating Codex Desktop:

1. Replace `codex-app/` with the new converted app.
2. Run the local apply helper against `resources/app.asar`.
3. Launch the app and verify the picker and skills bootstrap behavior.

Notes:

- The bundled fonts make Latin UI rendering deterministic across Linux
  machines. CJK glyphs still fall back to the system font stack unless more
  fallback fonts are added to this bundle later.
- The prod feature/runtime flags above are injected in code at runtime. This
  patch bundle does not edit the user's `~/.codex/config.toml`.
- The manifest targets the current bundle structure, so a future Codex release
  may need small manifest updates before reapplying cleanly.
