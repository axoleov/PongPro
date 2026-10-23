# Credits intro animation — design

**Date:** 2026-10-23 · **Size:** small change (one new scene, a one-line fix,
plus tests and screenshots)

## Intent

PongPro opens with a PONG PRO splash and never names anyone. The creator wants
**Aashirya Wilson D'Souza** shown at every launch as the sole credited person.
This is a school project that will be shown to a teacher, so the wording must
be exact and the presentation must look deliberate rather than busy.

## Goals

- Credits play **before** the existing splash on **every launch**:
  credits → PONG PRO → menu.
- A click skips **only the screen it is on**: credits → PONG PRO → menu.
- Fully animated in the game's existing visual language.
- The screen carries **exactly two lines of text**:
  `GAME CREATOR` and `AASHIRYA WILSON D'SOUZA`. Nothing else.
- Fix the splash's on-screen text: `PYGAME-CE` → `PYGAME 2.6.1`.

## Non-goals

- **No AI credit line** — removed at the creator's request.
- No "have seen this" flag, no settings toggle, no replay button.
- No voice-over or new audio.
- No new art style and no binary assets (the project ships zero).

## Constraints

- One class per screen is the established convention; boot starts in
  `SplashScene` (`app.py:122`).
- `SplashScene` defers audio loading to its *second* frame so Windows never
  marks the window "not responding". That must not be disturbed.
- Tests must stay headless — no display or audio device required.
- `tests/test_layout.py` gives every scene a `test_X_draws` plus a
  content-fits test; `tools/shots.py` renders screens to PNG for review.
- `--skip-splash` must still boot straight to the menu.

## Approaches considered

1. **A separate `CreditsScene` that hands off to `SplashScene`.** Matches the
   one-scene-per-screen convention, reuses the shared furniture (starfield,
   vignette, glowing panels, outlined titles, attract ball), leaves the boot
   trick untouched, and lets each screen be skipped independently — exactly
   the behaviour requested.
2. **`SplashScene` becomes one two-phase timeline.** Fewer files, but stacks
   new work onto the delicate boot code and couples the two skip states.
3. **A reusable "cinematic" engine** for future cutscenes. Most flexible, most
   code — overkill for a single screen.

**Chosen: 1.**

## What it looks like

Persistent across the whole intro: starfield + vignette backdrop, a slow
drifting particle field, the cycling P1→P2 accent colour, a thin progress line
along the bottom, and a pulsing `CLICK ANYWHERE TO SKIP`.

There are only **two pieces of text on screen, ever** — `GAME CREATOR` and
`AASHIRYA WILSON D'SOUZA`. Everything else is pure ornament: thin rule lines,
light and motion. That is how a single credit still reads as a deliberate,
rich opening rather than a placeholder.

**Beat 1 — 0.0–1.6 s — The label.** The backdrop settles; a thin rule line
draws itself outward from the centre; `GAME CREATOR` fades up beneath it in
wide letterspacing.

**Beat 2 — 1.6–4.0 s — The name.** Each letter of
`AASHIRYA WILSON D'SOUZA` resolves in sequence, rising a short distance while
fading in. When the last letter lands, one light sweep travels left→right
across the word and a soft glow blooms behind it.

**Beat 3 — 4.0–5.6 s — Hold, then hand-off.** A second rule draws itself below
the name. Everything then holds *perfectly still* for about 1.6 s so the line
can actually be read, before fading and drifting upward as the state machine's
fade takes over and `SplashScene` replaces this scene.

Total ≈ **5.6 s**, plus the existing 2.2 s splash ≈ **7.8 s to the menu** if
never touched. One click during credits lands on PONG PRO; one click there
lands on the menu.

## Decisions

- New file `src/pongpro/scenes/credits.py`, class `CreditsScene`.
- **Skip:** any `MOUSEBUTTONDOWN` *or* `KEYDOWN` → immediately replace with
  `SplashScene()`. Mouse is what was asked for; keyboard comes along free and
  keeps the two screens behaving alike, since the existing splash already
  accepts both.
- **Guard:** ignore input while `self.stack.transitioning`. The stack swallows
  `KEYDOWN` during a fade but *not* mouse clicks, so without this a click
  during the fade-out would double-fire.
- **Copy is fixed and minimal** — the two lines above, and nothing more.
  Rendered in caps to match the rest of the game's typography
  (`PONG PRO`, `PRODUCTION EDITION`, `FOCUS`), and spelled exactly as given:
  `AASHIRYA WILSON D'SOUZA`.
- `app.py` boots `CreditsScene()` instead of `SplashScene()`.
- `--skip-splash` keeps replacing the boot scene with the menu, and therefore
  now skips the credits too.
- **Splash fix:** `f"v{__version__}  ·  PYTHON 3.12  ·  PYGAME-CE"` →
  `...  ·  PYGAME 2.6.1`. (The runtime really is plain pygame 2.6.1 — nothing
  in the project uses pygame-ce.)

## Checks to add and run

- `tests/test_layout.py`: `test_credits_draws` plus a content-fits test,
  following the pattern every other scene already has.
- A test that a click advances credits → splash, and that `--skip-splash`
  lands on the menu.
- `tools/shots.py`: render the credits screen; update the README's screen
  count to match.
- Run the full test suite, `tools/check_imports.py`, `tools/shots.py`, and a
  real boot check with `tools/check_exe.py`.

## Left to the builder

Exact pixel positions, easing curves and particle details — all inside the
conventions above.
