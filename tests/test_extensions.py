"""Local extensions: discovery, broken modules isolated, page blocks, actions, reload through the API."""
from __future__ import annotations

import textwrap

GOOD = textwrap.dedent('''
    TITLE = "My desk"
    REFRESH = 20
    STATE = {"n": 0}

    async def page(ctx):
        return {"blocks": [{"type": "kv", "title": "Count", "items": [["n", STATE["n"]]]},
                           {"type": "input", "action": "add", "placeholder": "number"},
                           "not a block"]}

    def action(ctx, payload):
        STATE["n"] += int(payload["text"])
        return {"message": f"now {STATE['n']}"}
''')


def _write(home, name, code):
    folder = home / "extensions"
    folder.mkdir(exist_ok=True)
    (folder / name).write_text(code, encoding="utf-8")


def test_extension_page_and_action(tmp_path, client):
    _write(tmp_path, "mydesk.py", GOOD)
    _write(tmp_path, "broken.py", "raise RuntimeError('boom')\n")
    _write(tmp_path, "_helper.py", "x = 1\n")                       # leading underscore: not an extension
    items = {e["name"]: e for e in client.post("/api/extensions/reload").json()["items"]}
    assert set(items) == {"mydesk", "broken"}
    assert items["mydesk"]["title"] == "My desk" and items["mydesk"]["refresh"] == 20 and items["mydesk"]["actions"]
    assert "boom" in items["broken"]["error"]

    page = client.get("/api/ext/mydesk").json()
    assert [b["type"] for b in page["blocks"]] == ["kv", "input"]  # junk entries dropped
    assert page["blocks"][0]["items"] == [["n", 0]]
    res = client.post("/api/ext/mydesk/action", json={"action": "add", "text": "5"}).json()
    assert res == {"message": "now 5"}
    assert client.get("/api/ext/mydesk").json()["blocks"][0]["items"] == [["n", 5]]   # cache dropped after the action

    assert "boom" in client.get("/api/ext/broken").json()["error"]
    assert "error" in client.get("/api/ext/missing").json()


def test_extensions_can_be_switched_off(tmp_path, client):
    _write(tmp_path, "mydesk.py", GOOD)
    client.patch("/api/settings", json={"extensions_enabled": False})
    assert client.post("/api/extensions/reload").json()["items"] == []


def test_bundled_example_extension_runs(tmp_path, client):
    from pathlib import Path
    example = Path(__file__).resolve().parents[1] / "examples" / "extensions" / "watch_gap.py"
    _write(tmp_path, "watch_gap.py", example.read_text(encoding="utf-8"))
    client.post("/api/extensions/reload")
    page = client.get("/api/ext/watch_gap").json()
    assert "error" not in page, page
    table = next(b for b in page["blocks"] if b["type"] == "table")
    assert table["rows"] and all(r["chg"].endswith("%") for r in table["rows"])


def test_extensions_contribute_today_blocks(tmp_path, client):
    _write(tmp_path, "vola.py", "TITLE = 'Vola'\n"
           "def page(ctx):\n    return {'blocks': []}\n"
           "async def today(ctx):\n    return {'blocks': [{'type': 'kv', 'title': 'Traffic light', 'items': [['DAX', 'MID']]}, 'junk']}\n")
    _write(tmp_path, "broken_today.py", "def page(ctx):\n    return {'blocks': []}\n"
           "def today(ctx):\n    raise RuntimeError('no data')\n")
    client.post("/api/extensions/reload")
    blocks = client.get("/api/extensions/today").json()["blocks"]
    kv = next(b for b in blocks if b["type"] == "kv")
    assert kv["extension"] == "vola" and kv["items"] == [["DAX", "MID"]]
    assert any(b["type"] == "note" and "no data" in b["text"] for b in blocks)      # a failing hook shows a note
