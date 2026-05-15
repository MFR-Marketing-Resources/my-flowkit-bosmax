import asyncio
import json
import aiohttp
import sys

BASE_URL = "http://127.0.0.1:8100"

async def run_diagnostic():
    async with aiohttp.ClientSession() as session:
        # Step 1: Health
        print("--- STEP 1: HEALTH ---")
        async with session.get(f"{BASE_URL}/health") as resp:
            health = await resp.json()
            print(f"HEALTH_JSON: {json.dumps(health)}")

        if not health.get("extension_connected"):
            print("STATUS: AGENT_NOT_CONNECTED_TO_EXTENSION")
            return

        # Step 2: Open Flow Tab itself
        print("\n--- STEP 2: OPEN FLOW TAB ---")
        async with session.post(f"{BASE_URL}/api/operator/open-flow-new-project", json={"mode": "F2V"}) as resp:
            open_result = await resp.json()
            print(f"OPEN_RESULT: {json.dumps(open_result)}")

        # Step 3: Readiness check
        print("\n--- STEP 3: READINESS ---")
        async with session.post(f"{BASE_URL}/api/operator/flow-readiness-smoke", json={"mode": "F2V"}) as resp:
            smoke = await resp.json()
            print(f"READINESS_JSON: {json.dumps(smoke)}")

        # Step 4: Tab Audit
        # This information is partly in 'smoke' but we want a full audit.
        # I'll look for TABS_SEEN_BY_EXTENSION in the smoke output if available.
        
        # Step 5: Page State Diagnostic (Extra proof)
        print("\n--- STEP 5: PAGE STATE DIAGNOSTIC ---")
        async with session.post(f"{BASE_URL}/api/operator/flow-page-state-diagnostic", json={"mode": "F2V"}) as resp:
            diag = await resp.json()
            print(f"DIAGNOSTIC_JSON: {json.dumps(diag)}")

if __name__ == "__main__":
    asyncio.run(run_diagnostic())
