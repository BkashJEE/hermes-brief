"""Spin the real routes on an aiohttp test server with a fake API-server auth check."""
import asyncio, json, sqlite3, sys, types, pathlib, importlib.util
ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("hermes_brief", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
pkg = importlib.util.module_from_spec(spec); sys.modules["hermes_brief"] = pkg; spec.loader.exec_module(pkg)
from aiohttp import web
from aiohttp.test_utils import TestServer, TestClient
from hermes_brief.store import Store
from hermes_brief import service

class Adapter:
    def _check_auth(self, req):
        return None if req.headers.get("Authorization") == "Bearer good" else web.json_response({"e": 1}, status=401)

class LLM:
    async def acomplete_structured(self, **k):
        return types.SimpleNamespace(parsed={"headline": "Hackathon starts", "what_it_is": "An X post", "key_points": ["7 days", "$20K"],
                                              "why_it_matters": "entry window", "next_step": "build", "tags": ["nous"], "confidence": "full"}, model="m", provider="p")

async def main():
    store = Store(sqlite3.connect(":memory:", check_same_thread=False))
    app = web.Application()
    worker = service.Worker(store, lambda: LLM())
    service.wire_routes(app.router, Adapter(), store, worker, "default")
    app.on_startup.append(lambda a: worker.start() or asyncio.sleep(0))
    c = TestClient(TestServer(app)); await c.start_server()
    H = {"Authorization": "Bearer good"}
    assert (await c.get(f"{service.BASE}/status")).status == 401
    r = await c.post(f"{service.BASE}/items", headers=H, json={"url": "https://x.com/Teknium/status/2118099324186059220?s=20", "folder": "Hackathon", "content": "Post by Teknium: It's time for another hackathon! " * 6})
    item = await r.json(); assert r.status == 200 and item["folder"] == "Hackathon", item
    for _ in range(40):
        await asyncio.sleep(0.1)
        got = await (await c.get(f"{service.BASE}/items/{item['id']}", headers=H)).json()
        if got["status"] == "done": break
    assert got["brief"]["headline"] == "Hackathon starts", got
    look = await (await c.get(f"{service.BASE}/lookup", params={"url": "https://twitter.com/Teknium/status/2118099324186059220"}, headers=H)).json()
    assert look["item"]["id"] == item["id"]
    found = await (await c.get(f"{service.BASE}/items", params={"q": "hackathon"}, headers=H)).json()
    assert found["items"][0]["id"] == item["id"]
    mv = await (await c.post(f"{service.BASE}/items/{item['id']}/move", headers=H, json={"folder": "Done"})).json(); assert mv["folder"] == "Done"
    fol = await (await c.get(f"{service.BASE}/folders", headers=H)).json(); assert fol["folders"][0]["name"] == "Done"
    bad = await c.post(f"{service.BASE}/items", headers=H, json={"url": "javascript:alert(1)"}); assert bad.status == 400
    d = await (await c.delete(f"{service.BASE}/items/{item['id']}", headers=H)).json(); assert d["deleted"]
    await worker.stop(); await c.close(); print("routes: all ok")

asyncio.run(main())
