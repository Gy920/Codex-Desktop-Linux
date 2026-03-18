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
- keeps the Linux "Select project" flow working even when the file chooser only
  exposes file selection
- resolves a selected file back to its parent directory
- removes the `git clone --sparse` flag from recommended-skills bootstrap

Expected local workflow after updating Codex Desktop:

1. Replace `codex-app/` with the new converted app.
2. Run the local apply helper against `resources/app.asar`.
3. Launch the app and verify the picker and skills bootstrap behavior.

Notes:

- The bundled fonts make Latin UI rendering deterministic across Linux
  machines. CJK glyphs still fall back to the system font stack unless more
  fallback fonts are added to this bundle later.
- The manifest targets the current bundle structure, so a future Codex release
  may need small manifest updates before reapplying cleanly.
