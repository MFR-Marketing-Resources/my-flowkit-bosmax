# Hermes Agent Contract

## WAJIB BACA SEBELUM BUAT APA-APA

---

## PREFLIGHT CHECKLIST — Wajib sebelum setiap `edit_block`

Jangan skip satu pun. Kalau skip, `edit_block` AKAN gagal.

```
[ ] 1. grep -n untuk cari line number fungsi yang nak diedit
[ ] 2. sed -n 'X,Yp' untuk baca teks SEMASA dari fail
[ ] 3. Salin teks EXACT dari output sed sebagai old_string
[ ] 4. Baru hantar edit_block
```

### Command untuk Step 1 (grep):
```json
{
  "tool": "start_process",
  "parameters": {
    "command": "grep -n 'nama_fungsi_atau_pattern' /C/Users/USER/Desktop/_ref_flowkit/<path-to-file>",
    "timeout_ms": 10000
  }
}
```

### Command untuk Step 2 (sed — guna line number dari Step 1):
```json
{
  "tool": "start_process",
  "parameters": {
    "command": "sed -n '100,150p' /C/Users/USER/Desktop/_ref_flowkit/<path-to-file>",
    "timeout_ms": 10000
  }
}
```

### Command untuk Step 4 (edit_block):
```json
{
  "tool": "edit_block",
  "parameters": {
    "file_path": "/C/Users/USER/Desktop/_ref_flowkit/<path-to-file>",
    "old_string": "<teks EXACT dari output sed — jangan tulis dari ingatan>",
    "new_string": "<teks pengganti>"
  }
}
```

---

## Rules Yang Tak Boleh Dilanggar

| Perkara | Betul | Salah |
|---|---|---|
| Tool name untuk edit | `edit_block` | `patch` |
| Parameter name | `file_path` | `path`, `filepath` |
| Path format | `/C/Users/USER/Desktop/_ref_flowkit/...` | `C:\Users\...` atau `/home/...` |
| `old_string` source | Output `sed` yang baru dibaca | Ingatan / proposal lama |
| Fail besar (1000+ baris) | `start_process` + `sed`/`grep` | `read_file` tanpa offset |

### Error `{"error": "path required"}`
= Tool name salah (`patch` bukan `edit_block`) ATAU parameter `file_path` tiada.

### Error string not found / edit gagal
= `old_string` tak match teks semasa. Wajib buat Step 1→2 semula untuk baca teks terkini.

---

## Path & Environment

**Project root dalam container:**
```
/C/Users/USER/Desktop/_ref_flowkit/
```

**Fail-fail utama:**
```
extension/background.js       — 3200+ baris, MESTI guna sed/grep
extension/content-flow-dom.js — guna sed/grep
extension/side_panel.js
```

**Line endings:** Semua fail adalah LF. Tiada CRLF. Tiada isu line ending.

---

## Cara Baca Fail Besar (CONFIRMED BERJAYA)

`read_file` sahaja GAGAL untuk fail 1000+ baris. Guna cara ini:

```bash
# Cari line number
grep -n 'nama_fungsi' /C/Users/USER/Desktop/_ref_flowkit/extension/background.js

# Baca 50 baris dari line 2542
sed -n '2542,2592p' /C/Users/USER/Desktop/_ref_flowkit/extension/background.js
```

Kedua-dua command ini dijalankan melalui `start_process` dengan `timeout_ms: 10000`.

Path untuk `start_process` adalah SAMA dengan tool lain: `/C/Users/USER/Desktop/_ref_flowkit/...`
JANGAN guna `/home/...` — itu template generic yang tidak apply di sini.
