import asyncio, aiohttp, json
BASE_URL = 'http://127.0.0.1:8100'
async def r():
    async with aiohttp.ClientSession() as s:
        async with s.get(f'{BASE_URL}/health') as h:
            health = await h.json()
        async with s.post(f'{BASE_URL}/api/operator/open-flow-new-project', json={'mode': 'F2V'}) as o:
            open_res = await o.json()
        with open('scratch/diagnostic_result.json', 'w') as f:
            json.dump({"health": health, "open": open_res}, f)
asyncio.run(r())
