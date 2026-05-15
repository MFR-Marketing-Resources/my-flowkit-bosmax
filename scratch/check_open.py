import asyncio, aiohttp, json
BASE_URL = 'http://127.0.0.1:8100'
async def r():
    async with aiohttp.ClientSession() as s:
        async with s.get(f'{BASE_URL}/health') as h:
            print(f'HEALTH: {json.dumps(await h.json())}')
        async with s.post(f'{BASE_URL}/api/operator/open-flow-new-project', json={'mode': 'F2V'}) as o:
            print(f'OPEN: {json.dumps(await o.json())}')
asyncio.run(r())
