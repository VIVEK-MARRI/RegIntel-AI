import httpx, asyncio
from app.main import app

async def test():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
        endpoints = [
            '/api/v1/alerts',
            '/api/v1/changes',
            '/api/v1/leaders',
        ]
        for ep in endpoints:
            r = await client.get(ep)
            body = r.json()
            if isinstance(body, dict):
                print(f'{ep}: {r.status_code} - keys: {list(body.keys())}')
            else:
                print(f'{ep}: {r.status_code} - array len: {len(body)}')

asyncio.run(test())