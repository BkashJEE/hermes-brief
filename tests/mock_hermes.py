"""A stand-in Hermes for extension tests: the real plugin routes, a fake API key ('test-key'), a fake model,
a test article page and a tiny /v1/chat/completions stream. Run: python tests/mock_hermes.py [port]"""
import asyncio, json, sqlite3, sys, types, pathlib, importlib.util
ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("hermes_brief", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
pkg = importlib.util.module_from_spec(spec); sys.modules["hermes_brief"] = pkg; spec.loader.exec_module(pkg)
from aiohttp import web
from hermes_brief.store import Store
from hermes_brief import service

class Adapter:
    def _check_auth(self, req):
        return None if req.headers.get("Authorization") == "Bearer test-key" else web.json_response({"error": "no"}, status=401)

class LLM:
    async def acomplete_structured(self, input=None, **k):
        text = input[0]["text"]
        title = next((l[7:] for l in text.splitlines() if l.startswith("Title: ")), "")
        return types.SimpleNamespace(parsed={"headline": f"Brief of: {title}", "what_it_is": "A test page", "key_points": ["read by the browser" if "Inbox tip:" in text else "read by the server", f"{len(text)} chars"],
                                              "why_it_matters": "test", "next_step": "", "tags": ["test"], "confidence": "full"}, model="fake", provider="mock")

ARTICLE = "<html><head><title>Mock article about agents</title></head><body><nav>menu</nav><article><h1>Agents</h1><p>" + ("Hermes reads this paragraph. " * 40) + "</p><p>Inbox tip: only visible after login.</p></article></body></html>"

async def chat(req):
    body = await req.json()
    resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"}); await resp.prepare(req)
    q = body["messages"][-1]["content"]
    for word in ["You", " asked", " about", f" {len(q)} chars", "."]:
        await resp.write(f"data: {json.dumps({'choices': [{'delta': {'content': word}}]})}\n\n".encode()); await asyncio.sleep(0.05)
    await resp.write(b"data: [DONE]\n\n"); return resp

def main(port):
    store = Store(sqlite3.connect(":memory:", check_same_thread=False))
    app = web.Application()
    worker = service.Worker(store, lambda: LLM())
    service.wire_routes(app.router, Adapter(), store, worker, "mock")
    app.router.add_get("/test-article", lambda r: web.Response(text=ARTICLE, content_type="text/html"))
    app.router.add_post("/v1/chat/completions", chat)
    async def start(a): worker.start()
    app.on_startup.append(start)
    web.run_app(app, host="127.0.0.1", port=port, print=lambda *a: print("mock hermes on", port, flush=True))

if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8799)
