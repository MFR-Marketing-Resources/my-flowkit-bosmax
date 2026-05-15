import asyncio
import json
import aiohttp

BASE_URL = "http://127.0.0.1:8100"

async def run_verification():
    async with aiohttp.ClientSession() as session:
        # 1. Check health
        async with session.get(f"{BASE_URL}/health") as resp:
            health = await resp.json()
            extension_connected = health.get("extension_connected", False)

        # 2. Get status from agent
        async with session.get(f"{BASE_URL}/api/local-agent/status") as resp:
            status_data = await resp.json()
            
        # 3. Check Flow Page State (to verify content script)
        # We'll use the flow/status endpoint first
        async with session.get(f"{BASE_URL}/api/flow/status") as resp:
            flow_status = await resp.json()
            flow_key_present = flow_status.get("flow_key_present", False)

        # 4. Diagnostics/Status check
        # We need to call the internal get_status via the agent
        # The agent exposes this via /api/local-agent/status but we need the raw dict from the extension
        
        # I'll use a direct python script to talk to the agent's internal objects if needed, 
        # but the API should be enough if I can get the buildId.
        
        # Wait, local-agent/status calls client.get_status().
        # Let's check what it returns.
        
        # 5. Verify buildId and content script
        # I'll use the flow-page-state-diagnostic to verify content script and buildId
        diagnostic_payload = {"mode": "F2V"}
        # Wait, I need a request_id for execute-flow-job but diagnostics might not need it.
        # Actually, let's use the flow/diagnostic endpoint if it exists.
        
        # Looking at agent/api/flow.py, there isn't a direct diagnostic endpoint.
        # But there is execute-flow-job which I can use with a special "smoke_test" flag if supported?
        # No, let's just use the telemetry and status.
        
        print(f"FLOW_TAB_FOUND: {extension_connected}")
        
        # We need to get the buildId. I'll query the agent's memory or logs.
        # Actually, I'll just run a small script that uses the FlowClient directly to get status.
        pass

if __name__ == "__main__":
    asyncio.run(run_verification())
