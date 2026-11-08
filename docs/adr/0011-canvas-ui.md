# 0011. Split-screen canvas: live app plus a pannable workflow, Metallic Chic

- **Status:** Accepted, 2026-11-08
- **Supersedes:** the Jade Pebble Morning palette and Times New Roman/NYT type choices made earlier
  that day

## Context

The PDF demo puts the agent's app on the left and the monitor on the right. The owner asked for:
- a Zapier-like workflow page that moves with the mouse, with a dot-grid background;
- one agent instead of separate careful and faulty agents (ADR 0010);
- bigger elements for presenting;
- the "Metallic Chic" style (Shopify Editions reference).

## Decision

- **Layout.**
  - Left: the real workspace app in an iframe, following each step's page and reloading after
    it, with manual tabs.
  - Right: the workflow canvas plus a monitor strip (risk line, all steps).
  - A resizable divider. Under 900 px the canvas comes first and the app opens as an overlay.
- **The canvas.** Pointer-drag and pinch to pan; ctrl/⌘+wheel and buttons to zoom; Fit and
  Follow the agent; arrow keys and +/− when focused. Dot grid on white space. Electric edges while
  a step is checked; no animation under reduced motion.
- **Style.** Palette `#3D52A0 #7091E6 #8697C4 #ADBBDA #EDE8F5`, with amber and brick for
  paused and blocked only. Archivo: a thin, wide display headline and normal-width text. White
  "block" surfaces with indigo-tinted shadows. Light and dark. The logo is recolored to the
  palette; the workspace apps keep their own lookalike styling.
- **Framing.** When framed by the canvas, the workspace hides its own app bar. Opened directly,
  it's unchanged.
- **Fixture mode** (`?fixture=1`) replays canned responses, for UI work without the server.
- **Reset world** stays available while a pause waits, and abandons that run.

## Consequences

- The demo shows the apps really changing next to the checks that allowed or stopped each change.
- The workspace apps load Tailwind from its CDN, as on the sales-env branch. The browser warns
  about it but it's harmless for a demo. Precompiling the CSS is a follow-up.
