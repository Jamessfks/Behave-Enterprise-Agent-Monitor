# Logo image prompt

For the header of Agent Monitor (`web/index.html`, the `.brand` block). Image models draw text
badly, so generate the **mark only** and keep the "Agent Monitor" wordmark as live text in Geist.
The header already sets it that way.

## Prompt (mark only, recommended)

```text
A minimalist logo mark for "Agent Monitor", software that checks every step an AI agent takes
before it counts. Concept: a single vertical line, the flow of work, passing through a small
rounded-square checkpoint. Inside the checkpoint sits one solid dot, the step being checked. A
short, clean spark of light crosses the line just above the checkpoint, suggesting a current
flowing through it. Flat vector style, geometric, perfectly symmetrical, thick even strokes with
rounded ends, generous negative space, readable at 24 pixels. Exactly two colours: deep moss
green #404E3B for the line and checkpoint, soft jade green #7B9669 for the dot and the spark.
Plain flat background in pale pebble grey #E6E6E6. Centered, square 1:1 canvas, the mark filling
about 60% of it. Calm, precise, trustworthy, elegant, like a premium developer tool.
```

**Avoid (negative prompt):** text, letters, words, gradients, 3D, bevels, shadows, glow halos,
glossy effects, shields, eyes, robots, brains, circuit-board patterns, lightning bolts, mascots,
busy detail, more than two colours, photorealism, mockups, frames.

## Variant (mark + wordmark lockup)

Use it only if you want the text baked into the image. Check the spelling closely.

```text
A horizontal logo lockup: on the left, a minimalist mark of a vertical line passing through a
small rounded-square checkpoint with a solid dot inside and a short spark crossing the line;
on the right, the words "Agent Monitor" in a clean geometric sans-serif (like Geist or Inter),
medium weight, sentence case, tight but even letter spacing. Mark in deep moss green #404E3B
with a jade #7B9669 dot and spark; text in #404E3B. Flat vector, no gradients or shadows, plain
pebble-grey #E6E6E6 background, wide 4:1 canvas, lots of breathing room.
```

## Dark-mode version

Rerun the mark prompt with: line and checkpoint in sage #BAC8B1, dot and spark in #94B382, on a
very dark moss background #161C14.

## Before uploading

- **Format:** SVG is best; vectorize the PNG (e.g. with a tracing tool), or export a transparent
  PNG at 256×256 or larger.
- **Size in the header:** the mark shows at 28×28 px. Check that it still reads at that size.
- **Where it goes:** save it as `web/logo.svg` (and `web/logo-dark.svg` if you made one). Then it
  replaces the inline mark in the header and the favicon (`web/favicon.svg`).
