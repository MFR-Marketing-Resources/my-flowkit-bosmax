# AI Debugging Contract Router

Whenever the user provides a short command or a bug-related phrase, follow the routing instructions here.

## Trigger Phrases
- "fix this bug"
- "debug this"
- "repair this error"
- "macam mana ni"
- "betulkan error ni"
- "cari root cause"
- "kenapa error"
- "tolong fix"

## Routing Logic
1. **Identify Task:** If the user command matches or implies any of the above, treat it as a formal debugging task.
2. **Load Contract:** Immediately read and adhere to [.ai/contracts/DEBUG_CONTRACT.md](file:///c:/Users/USER/Desktop/_ref_flowkit/.ai/contracts/DEBUG_CONTRACT.md).
3. **Specialized Context:** If the bug is related to the Chrome Extension (MV3), also load [.ai/contracts/CHROME_EXTENSION_MV3_DEBUG_CONTRACT.md](file:///c:/Users/USER/Desktop/_ref_flowkit/.ai/contracts/CHROME_EXTENSION_MV3_DEBUG_CONTRACT.md).
4. **Report Format:** Use [.ai/contracts/ROOT_CAUSE_REPORT_FORMAT.md](file:///c:/Users/USER/Desktop/_ref_flowkit/.ai/contracts/ROOT_CAUSE_REPORT_FORMAT.md) for the final response.

Short user commands are sufficient to trigger this full protocol. The user does not need to restate the contract.
