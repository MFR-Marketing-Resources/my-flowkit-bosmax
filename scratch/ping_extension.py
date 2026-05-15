import asyncio
import sys
import json
from agent.services.flow_client import ping_flow_dom_script, get_flow_tab
from agent.services.extension_messaging import send_extension_message, get_connected_extension

async def main():
    print("Testing extension connectivity...")
    ws = get_connected_extension()
    if not ws:
        print(json.dumps({"error": "No connected extension websocket"}))
        return

    print("Checking for Flow tab...")
    tab = await get_flow_tab()
    if not tab:
        print(json.dumps({"error": "No active Flow tab found"}))
        return

    print(f"Flow tab found: ID {tab['id']}, URL {tab['url']}")
    
    print("Sending STATUS ping to background...")
    try:
        status_resp = await send_extension_message({
            "type": "EVAL_BACKGROUND",
            "code": "new Promise(resolve => chrome.runtime.sendMessage({type: 'STATUS'}, resolve))"
        })
        print(f"Background STATUS response: {status_resp}")
    except Exception as e:
        print(f"Background STATUS failed: {e}")

    print("Pinging content script...")
    health = await ping_flow_dom_script(tab)
    print(f"Content script health: {health}")

if __name__ == "__main__":
    asyncio.run(main())
