# Hermes Agent Contract

Read AGENTS.md first, then this file.

## Role
Hermes = implementation agent using MCP_DOCKER (Desktop Commander) tools for file edits.

## MCP_DOCKER Tool Rules — MANDATORY

### Path Format
All file paths MUST use Linux container format:
```
/C/Users/USER/Desktop/_ref_flowkit/<relative-path>
```
NOT Windows format: `C:\Users\USER\Desktop\_ref_flowkit\...`

### edit_block (patch tool)

> ⚠️ Tool name is `edit_block` — NOT `patch`. There is NO tool named `patch` in MCP_DOCKER.

Parameter name is `file_path` — NOT `path`, NOT `filepath`. No `mode`, no `replace_all`.

```json
{
  "tool": "edit_block",
  "parameters": {
    "file_path": "/C/Users/USER/Desktop/_ref_flowkit/extension/background.js",
    "old_string": "exact text to find",
    "new_string": "replacement text"
  }
}
```

`{"error": "path required"}` = tool name salah (`patch` instead of `edit_block`) OR `file_path` param missing.

### read_file
Accepts both Windows and Linux paths. Linux path preferred for consistency.

### write_file
Use Linux path. Max 50 lines per call — split large writes into chunks.

### start_process
Use for shell commands inside the container. Linux commands only (`ls`, `cat`, `grep`).

## Line Endings
All project files are LF (normalized via `.gitattributes`). No CRLF handling needed.

## Project Root (inside container)
```
/C/Users/USER/Desktop/_ref_flowkit/
```
