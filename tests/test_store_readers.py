import asyncio, json, sqlite3, sys, types, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
import importlib
hb = importlib.import_module(ROOT.name.replace('-', '_')) if False else None
spec = importlib.util.spec_from_file_location("hermes_brief", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
pkg = importlib.util.module_from_spec(spec); sys.modules["hermes_brief"] = pkg
# fake plugins.plugin_storage
storage = types.ModuleType("plugins.plugin_storage"); storage.plugin_db = lambda name: sqlite3.connect(":memory:", check_same_thread=False)
sys.modules["plugins"] = types.ModuleType("plugins"); sys.modules["plugins.plugin_storage"] = storage
spec.loader.exec_module(pkg)
from hermes_brief.store import Store, canonical_url
from hermes_brief import readers, brief as B, tools as T

def test_canonical():
    assert canonical_url("https://twitter.com/a/status/123/photo/1?s=20&t=abc") == "https://x.com/a/status/123"
    assert canonical_url("https://youtu.be/XYZ?si=foo") == "https://youtube.com/watch?v=XYZ"
    assert canonical_url("https://www.example.com/post/?utm_source=x#top") == "https://example.com/post"

def test_save_dedupes_and_keeps_content():
    s = Store(sqlite3.connect(":memory:"))
    a = s.save(url="https://example.com/a?utm_source=x", title="A", content="x" * 500)
    b = s.save(url="https://example.com/a", folder="AI")
    assert a["id"] == b["id"] and b["folder"] == "AI"
    assert len(s.get(a["id"], with_content=True)["content"]) == 500
    assert s.folders()[0]["name"] == "AI"
    assert s.search(query="a")[0]["id"] == a["id"]

def test_kinds():
    assert readers.kind_of("https://x.com/u/status/1") == "x_post"
    assert readers.kind_of("https://www.youtube.com/watch?v=1") == "youtube"
    assert readers.kind_of("https://example.com") == "page"

def test_vtt():
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nhello there\n\n00:00:25.000 --> 00:00:27.000\nsecond part\n00:00:26.000 --> 00:00:28.000\nsecond part\n"
    out = readers.vtt_to_text(vtt)
    assert "[0:01] hello there" in out and "[0:25] second part" in out and out.count("second part") == 1

def test_html():
    t, body, meta = readers.html_to_text("<html><head><title>T</title><meta property='og:description' content='D'></head><body><nav>menu</nav><article><p>" + "word " * 120 + "</p></article><script>x()</script></body></html>")
    assert t == "T" and "menu" not in body and "x()" not in body and meta["og:description"] == "D"

class FakeLLM:
    def __init__(self): self.calls = 0
    def _res(self):
        self.calls += 1
        return types.SimpleNamespace(parsed={"headline": "H", "what_it_is": "A page", "key_points": ["a", "b"], "why_it_matters": "w",
                                              "next_step": "n", "tags": ["t"], "confidence": "full", "timestamps": [{"t": "0:01", "note": "x"}]},
                                     text="", model="m", provider="p")
    def complete_structured(self, **k): return self._res()
    async def acomplete_structured(self, **k): return self._res()

def test_worker_briefs_and_drops_timestamps_for_pages(monkeypatch=None):
    from hermes_brief.service import Worker
    s = Store(sqlite3.connect(":memory:"))
    it = s.save(url="https://example.com/a", title="A", content="y" * 400)
    llm = FakeLLM(); w = Worker(s, lambda: llm)
    asyncio.run(w.brief_one(s.get(it["id"], with_content=True)))
    got = s.get(it["id"])
    assert got["status"] == "done" and got["brief"]["headline"] == "H" and "timestamps" not in got["brief"] and got["meta"]["model"] == "p/m"
    md = B.brief_markdown(got)
    assert "**H**" in md and "Next step: n" in md

def test_worker_error_without_llm():
    from hermes_brief.service import Worker
    s = Store(sqlite3.connect(":memory:"))
    it = s.save(url="https://example.com/b", content="z" * 400)
    asyncio.run(Worker(s, lambda: None).brief_one(s.get(it["id"], with_content=True)))
    assert s.get(it["id"])["status"] == "error"

if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"): f(); print("ok", n)
