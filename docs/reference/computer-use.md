# Claude computer use — what Sentinel needs

From [platform.claude.com computer-use-tool docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool)
as of 2026-11-08. Reference implementation:
[anthropics/claude-quickstarts/computer-use-demo](https://github.com/anthropics/claude-quickstarts/tree/main/computer-use-demo).

## Tool declaration (Claude 5.5 models)

```json
{"type": "computer_toolset_20260801"}
```

- No beta header needed on `claude-opus-5-5` / `claude-sonnet-5-5` / `claude-haiku-5-5`. The
  quick start sends `anthropic-version: 2026-10-21`.
- No display-size params. Coordinates are in the pixel space of the screenshots *we* return.
- Image limits: 2,576 px long edge, about 3.75 MP. Oversized images are **rejected**, not
  downscaled. On a macOS Retina display, halve the coordinates or downscale screenshots 2×.
- Older tool `computer_20251124` (beta `computer-use-2025-11-24`) is for 4.x models only. 5.5
  models return 400 for it.

## Actions (each is its own tool name, dispatched on `toolset_name` + `name`)

`screenshot`, `zoom{region}`, `left_click{coordinate?, text?}`, `right_click`, `middle_click`,
`double_click`, `triple_click`, `left_click_drag{start_coordinate, coordinate}`,
`mouse_move{coordinate}`, `left_mouse_down`, `left_mouse_up`, `cursor_position`,
`scroll{scroll_direction, scroll_amount, coordinate?}`, `type{text}`, `key{text, repeat?}`,
`hold_key{text, duration}`, `wait{duration}`.

```json
{"type": "tool_use", "id": "toolu_…", "name": "left_click",
 "toolset_name": "computer", "input": {"coordinate": [512, 742]}}
```

Return one `tool_result` per `tool_use` in a single user message, echoing `toolset_name`.
`screenshot`/`zoom` return an image block, the rest return text such as `"OK"`. In a batch, stop
at the first failure and answer the rest with `is_error: true` and
`"Not executed: an earlier computer action in this turn failed."`

## Agent loop

```python
for _ in range(max_iterations):
    resp = client.messages.create(model="claude-opus-5-5", max_tokens=4096,
                                  messages=messages, tools=[{"type": "computer_toolset_20260801"}])
    messages.append({"role": "assistant", "content": resp.content})
    results = run_tool_calls(resp)          # ← Sentinel hook goes here
    if not results:
        break
    messages.append({"role": "user", "content": results})
```

## Where Sentinel plugs in

Raw computer-use actions are **pixels and keystrokes** ("left_click at 512,742"), not semantic
actions. Two ways to get catalog events:

1. **Environment emits events (recommended).** Our fake web app knows "the CRM Save button was
   clicked for lead X" and posts `{action_id, ...}` to the monitor. The agent log is kept only for
   display.
2. Map the agent's tool calls to actions (screenshot + coordinates → which element). This is
   fragile, so only use it if (1) is blocked.

**Pause/resume:** run the monitor check inside `run_tool_calls` *before* executing irreversible
clicks, or between loop iterations. When the monitor flags, stop the loop and wait for
Approve/Stop from the UI. On Approve, continue with the same `messages`.

## Security (from the docs; applies to the demo)

- Run in a dedicated VM or container with minimal privileges, and give it no real credentials.
- Allowlist network access to the fake environment's host.
- Content in pages or screenshots can prompt-inject the agent. Our seeded emails are ours, but
  keep that in mind if anyone adds "realistic" phishing content.
