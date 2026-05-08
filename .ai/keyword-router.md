# AI Debugging Contract Router

Whenever the user provides a short command or a bug-related phrase, the agent MUST automatically load the debugging framework.

## Trigger Phrases
- "fix this bug"
- "debug this"
- "repair this error"
- "error ni"
- "macam mana ni"
- "betulkan error ni"
- "cari root cause"

## Mandatory Loading Sequence
1. Load **[.ai/keyword-router.md](file:///c:/Users/USER/Desktop/_ref_flowkit/.ai/keyword-router.md)**
2. Load **[.ai/contracts/DEBUG_CONTRACT.md](file:///c:/Users/USER/Desktop/_ref_flowkit/.ai/contracts/DEBUG_CONTRACT.md)**
3. For Chrome Extension MV3 bugs, load **[.ai/contracts/CHROME_EXTENSION_MV3_DEBUG_CONTRACT.md](file:///c:/Users/USER/Desktop/_ref_flowkit/.ai/contracts/CHROME_EXTENSION_MV3_DEBUG_CONTRACT.md)**

## Global Rule
The user must never need to paste the full debugging contract again. Short commands are enough to trigger the full protocol.
Agents must follow the MV3 Hard Rules: mapping topology, auditing listeners/senders, and checking lifecycle states.
