import asyncio
from agent.services.flow_client import get_flow_client

async def main():
    client = get_flow_client()
    if not client.connected:
        print("Extension not connected")
        return

    print("Extension connected.")
    print("Testing flow page diagnostic...")
    try:
        diag = await client.flow_page_state_diagnostic()
        print(f"Diagnostic result: {diag}")
    except Exception as e:
        print(f"Diagnostic failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
