import httpx, asyncio
from app.main import app

async def test():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
        endpoints = [
            '/api/v1/agents/workflows',
            '/api/v1/agents/workflows?page=1&page_size=10',
        ]
        for ep in endpoints:
            r = await client.get(ep)
            body = r.json()
            print(f'{ep}: {r.status_code}')
            if r.status_code != 200:
                print(f'  body: {body}')

asyncio.run(test())