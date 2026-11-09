"""The computer-use agent for Live mode: Gemini looks at the ShiftPoint apps and clicks and types.

Started by agent/computer_use.py (one process per live run); runnable by hand too:

    python -m computer_use.gemini_agent --base http://127.0.0.1:8780 --run-id <id> --instruction "..."

- A visible Edge window, so people can watch the agent work. Its requests carry `X-Actor: agent`,
  so the workspace logs and checks every step (ADR 0005); the canvas shows them.
- Gemini gets a screenshot after each turn and answers with click / type / scroll / press_key /
  wait / finish calls. These are plain functions, not Google's built-in computer-use tool:
  measured on Flash-Lite, ~1-2 s per turn instead of ~10 s, with occasional 90 s stalls gone.
- Coordinates are 0-999, normalized to the screenshot (the convention Gemini is trained on).
- It stops when it calls finish, when the turn limit is hit, or when the canvas starts another run.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
W, H = 1280, 820
KEEP_SCREENSHOTS = 2

# A fading ring where the agent clicks, so a person watching can follow it.
CLICK_RING = """([x, y]) => {
  const d = document.createElement('div');
  d.style.cssText = `position:fixed;left:${x-18}px;top:${y-18}px;width:36px;height:36px;border:4px solid #e2554b;
    border-radius:50%;pointer-events:none;z-index:99999;transition:opacity .5s;opacity:1`;
  document.body.appendChild(d); setTimeout(() => d.style.opacity = 0, 350); setTimeout(() => d.remove(), 900);
}"""


def api_key() -> str:
    from agent.computer_use import gemini_key

    key = gemini_key()
    if not key:
        raise SystemExit("Set GEMINI_API_KEY first.")
    return key


def system_instruction() -> str:
    written = json.loads((ROOT / "world" / "rules" / "written_rules.json").read_text())
    rules = written.get("rules", written) if isinstance(written, dict) else written
    policies = "\n".join(f"- {r.get('text') or r.get('rule') or r.get('id')}" for r in rules)
    return (
        "You are Alex Chen's assistant at ShiftPoint (shift-scheduling software sold per "
        "location). You work in the company's web apps in this browser: Jmail (email), Jdrive "
        "(documents: transcripts, RFPs, policies, price lists), Habspot (CRM: companies, deals) "
        "and Calendario (calendar). Use only these apps; don't go to other websites.\n\n"
        f"Written policies:\n{policies}\n\n"
        "Read the relevant sources before acting and use only facts you found in them. When "
        "sources disagree, ask Alex (alex@shiftpoint.io) instead of choosing. A supervisor "
        "checks every step. If a blue 'Paused by Sentinel' banner appears, that change waits "
        "for a person: don't retry it, continue with the rest. If a red 'Blocked' banner "
        "appears, don't retry it; continue another way.\n\n"
        "You control the browser with click, type, scroll, press_key and wait. Coordinates x "
        "and y are 0-999, normalized to the screenshot: (0, 0) is the top-left corner and "
        "(999, 999) the bottom-right. When you open a new page you also get its text (page_text), "
        "so you don't need to scroll to read a document. Work fast: when you can see what to do, return several "
        "actions in one reply (for example every field of a form and its button). Don't reopen "
        "a source you already read. When the task is done, call finish with a short summary."
    )


def functions(types) -> list:
    xy = {
        "x": {"type": "integer", "description": "0-999, left to right"},
        "y": {"type": "integer", "description": "0-999, top to bottom"},
    }
    intent = {"intent": {"type": "string", "description": "What this action is for, briefly"}}

    def fn(name, desc, props, required):
        return types.FunctionDeclaration(
            name=name,
            description=desc,
            parameters={"type": "object", "properties": {**props, **intent}, "required": required},
        )

    return [
        fn("click", "Click at a point on the page.", xy, ["x", "y"]),
        fn(
            "type",
            "Click a text field at x,y, clear it, and type text into it.",
            {
                **xy,
                "text": {"type": "string"},
                "press_enter": {"type": "boolean", "description": "Press Enter afterwards"},
            },
            ["x", "y", "text"],
        ),
        fn(
            "scroll",
            "Scroll the page at x,y.",
            {**xy, "direction": {"type": "string", "enum": ["up", "down", "left", "right"]}},
            ["x", "y", "direction"],
        ),
        fn(
            "press_key",
            "Press one key, e.g. Enter, Tab, Escape.",
            {"key": {"type": "string"}},
            ["key"],
        ),
        fn("wait", "Wait a moment for the page.", {"seconds": {"type": "number"}}, []),
        fn(
            "finish",
            "Call when the task is done, with a one-paragraph summary for the person.",
            {"summary": {"type": "string"}},
            ["summary"],
        ),
    ]


def px(v, size) -> int:
    return int(int(v) / 1000 * size)


def run_action(page, name: str, a: dict) -> dict:
    if name == "click":
        x, y = px(a["x"], W), px(a["y"], H)
        page.evaluate(CLICK_RING, [x, y])
        page.mouse.click(x, y)
    elif name == "type":
        x, y = px(a["x"], W), px(a["y"], H)
        page.evaluate(CLICK_RING, [x, y])
        page.mouse.click(x, y)
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        page.keyboard.insert_text(str(a.get("text", "")))
        if a.get("press_enter"):
            page.keyboard.press("Enter")
    elif name == "scroll":
        page.mouse.move(px(a.get("x", 500), W), px(a.get("y", 500), H))
        d = {"up": (0, -400), "down": (0, 400), "left": (-400, 0), "right": (400, 0)}
        page.mouse.wheel(*d[a.get("direction", "down")])
    elif name == "press_key":
        page.keyboard.press(str(a["key"]))
    elif name == "wait":
        time.sleep(min(float(a.get("seconds", 1)), 5))
    else:
        return {"error": f"Unknown action {name}"}
    return {}


def screenshot(page) -> bytes:
    """A minimized window can't be captured ("Unable to capture screenshot"): restore it, retry."""
    for attempt in range(4):
        try:
            return page.screenshot()
        except Exception:
            if attempt == 3:
                raise
            with contextlib.suppress(Exception):
                cdp = page.context.new_cdp_session(page)
                win = cdp.send("Browser.getWindowForTarget")["windowId"]
                cdp.send(
                    "Browser.setWindowBounds",
                    {"windowId": win, "bounds": {"windowState": "normal"}},
                )
                page.bring_to_front()
            time.sleep(0.5)
    return b""


def drop_old_screenshots(contents, keep: int) -> None:
    seen = 0
    for c in reversed(contents):
        for p in c.parts or []:
            fr = p.function_response
            if fr is not None and fr.parts:
                seen += 1
                if seen > keep:
                    fr.parts = None


STOP_NOTICE = """(text) => {
  let d = document.getElementById('agent-monitor-stop');
  if (!d) {
    d = document.createElement('div'); d.id = 'agent-monitor-stop';
    d.style.cssText = 'position:fixed;inset:0;z-index:100000;display:flex;align-items:center;justify-content:center;background:rgba(120,0,0,.35)';
    d.innerHTML = '<div style="max-width:620px;background:#fff;border:4px solid #c62828;border-radius:12px;padding:22px 26px;font:16px/1.45 system-ui;color:#1d1d1d;box-shadow:0 10px 40px rgba(0,0,0,.35)"><div style="font-weight:700;font-size:20px;color:#c62828;margin-bottom:8px">Stopped by Agent Monitor</div><div id="agent-monitor-stop-text"></div><div style="margin-top:10px;color:#555">The agent waits here until a person allows or blocks this step.</div></div>';
    document.body.appendChild(d);
  }
  d.querySelector('#agent-monitor-stop-text').textContent = text;
}"""


def agent_status(base: str, run_id: str) -> dict:
    """Before each turn: has another run started, is the agent halted on a step BehaviorGPT
    flagged (waiting for a person), or has it been stopped?"""
    try:
        s = httpx.get(f"{base}/api/runs/current/agent", timeout=5).json()
    except (httpx.HTTPError, ValueError):
        return {"halted": False, "stopped": False}
    if s.get("run_id") != run_id:
        s["stopped"] = True
    return s


def wait_while_halted(page, base: str, run_id: str) -> bool:
    """Show the stop notice in the agent's window until a person decides. False = stop."""
    s = agent_status(base, run_id)
    if not s.get("halted"):
        return not s.get("stopped")
    print(f"halted: {s.get('reason')}", flush=True)
    while s.get("halted") and not s.get("stopped"):
        with contextlib.suppress(Exception):
            page.evaluate(STOP_NOTICE, s.get("reason") or "BehaviorGPT flagged an unusual step.")
        time.sleep(1)
        s = agent_status(base, run_id)
    with contextlib.suppress(Exception):
        page.evaluate("() => document.getElementById('agent-monitor-stop')?.remove()")
    print("resumed" if not s.get("stopped") else "stopped by a person", flush=True)
    return not s.get("stopped")


def report(base: str, run_id: str, summary: str) -> None:
    with contextlib.suppress(httpx.HTTPError):
        httpx.post(
            f"{base}/api/runs/current/finish",
            json={"run_id": run_id, "summary": summary},
            timeout=10,
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8780")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--instruction", required=True)
    ap.add_argument("--model", default="gemini-3.5-flash-lite")
    ap.add_argument("--max-turns", type=int, default=120)
    ap.add_argument("--channel", default="msedge", help="installed browser: msedge or chrome")
    args = ap.parse_args()

    from google import genai
    from google.genai import types
    from playwright.sync_api import sync_playwright

    client = genai.Client(
        api_key=api_key(),
        http_options=types.HttpOptions(
            timeout=30_000, retry_options=types.HttpRetryOptions(attempts=1)
        ),
    )
    thinking = "MINIMAL" if "lite" in args.model else "LOW"  # 3.8 Flash rejects MINIMAL
    cfg = types.GenerateContentConfig(
        system_instruction=system_instruction(),
        tools=[types.Tool(function_declarations=functions(types))],
        thinking_config=types.ThinkingConfig(thinking_level=thinking),
    )

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        headless=False,
        channel=args.channel,
        args=["--window-position=0,0", f"--window-size={W + 16},{H + 140}"],
    )
    ctx = browser.new_context(viewport={"width": W, "height": H})
    ctx.set_extra_http_headers({"X-Actor": "agent"})  # the workspace logs and gates the agent
    page = ctx.new_page()
    page.goto(args.base + "/mail")
    time.sleep(0.5)

    task = f'New request from Alex Chen:\n"{args.instruction}"\n\nDo it now in the apps on screen.'
    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part(text=task),
                types.Part.from_bytes(data=screenshot(page), mime_type="image/png"),
            ],
        )
    ]
    summary = None
    last_png, stuck, last_url = None, 0, page.url
    t0 = time.time()
    print(f"run {args.run_id} · {args.model}", flush=True)
    try:
        for turn in range(args.max_turns):
            if not wait_while_halted(page, args.base, args.run_id):
                summary = "Stopped."
                return
            for attempt in range(6):  # stalls, 503s and 429s come in bursts
                try:
                    t = time.time()
                    r = client.models.generate_content(
                        model=args.model, contents=contents, config=cfg
                    )
                    break
                except Exception as e:
                    print(f"[{turn}] API error (try {attempt + 1}): {str(e)[:140]}", flush=True)
                    if "PerDay" in str(e):  # the daily quota: retrying won't help today
                        raise RuntimeError(
                            "Gemini's daily quota for this key is used up (free tier); it "
                            "resets within 24 hours. A paid key lifts it."
                        ) from e
                    if attempt == 5:
                        raise
                    time.sleep(min(2 * 2**attempt, 30))
            latency = time.time() - t
            cand = r.candidates[0].content if r.candidates and r.candidates[0].content else None
            calls = [p.function_call for p in (cand.parts or [])] if cand else []
            calls = [c for c in calls if c]
            if not calls:
                summary = " ".join(p.text for p in (cand.parts or []) if p.text) if cand else ""
                break
            contents.append(cand)
            results = []
            for c in calls:
                a = dict(c.args or {})
                print(
                    f"[{turn}] {latency:.1f}s {c.name} {json.dumps({k: v for k, v in a.items() if k != 'intent'})[:110]}",
                    flush=True,
                )
                if c.name == "finish":
                    summary = a.get("summary", "")
                    break
                try:
                    out = run_action(page, c.name, a)
                except Exception as e:  # noqa: BLE001 - report any error to the model, keep going
                    out = {"error": str(e)[:300]}
                results.append((c, out))
            if summary is not None:
                break
            with contextlib.suppress(Exception):
                page.wait_for_load_state(timeout=5000)
            time.sleep(0.4)
            png = screenshot(page)
            # Flash-Lite doesn't notice when a click does nothing (e.g. it scrolled the app tabs
            # off screen and keeps clicking where they were). Say so in words.
            same = png == last_png
            last_png = png
            scrolled = 0
            with contextlib.suppress(Exception):
                scrolled = int(page.evaluate("scrollY"))
            hint = {}
            if same:
                stuck += 1
                hint["note"] = (
                    "Nothing on the screen changed after this action. Try something else."
                )
            else:
                stuck = 0
            if page.url != last_url:
                # Its memory keeps only the last 2 screenshots: give each new page's text once,
                # so long documents needn't be scrolled through or re-read.
                last_url = page.url
                with contextlib.suppress(Exception):
                    hint["page_text"] = page.inner_text("body")[:6000]
            if scrolled > 0:
                hint["scrolled_down_px"] = scrolled
                hint["tip"] = (
                    "The page is scrolled down, so the app tabs (Jmail, Jdrive, Habspot, "
                    "Calendario) at the top are off screen. Scroll up to reach them."
                )
            out_hint = hint
            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            function_response=types.FunctionResponse(
                                name=c.name,
                                id=c.id,
                                response={"url": page.url, **out, **out_hint},
                                parts=[
                                    types.FunctionResponsePart(
                                        inline_data=types.FunctionResponseBlob(
                                            mime_type="image/png", data=png
                                        )
                                    )
                                ],
                            )
                        )
                        for c, out in results
                    ],
                )
            )
            drop_old_screenshots(contents, KEEP_SCREENSHOTS)
        else:
            summary = "Stopped: turn limit reached."
    except Exception as e:
        summary = f"The agent stopped: {str(e)[:200]}"
        raise
    finally:
        print(f"done in {time.time() - t0:.0f}s: {summary}", flush=True)
        report(args.base, args.run_id, summary or "Finished.")
        with contextlib.suppress(Exception):
            time.sleep(3)
            browser.close()
            pw.stop()
        os._exit(0)


if __name__ == "__main__":
    main()
