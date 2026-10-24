# Plan: Credits intro animation

**Spec:** `docs/superpowers/specs/2026-10-23-credits-intro-design.md` (approved)

## Goal

Add a fully animated credits screen that plays **before** the existing PONG PRO
splash on every launch, crediting the game's creator by name, and make the
splash's on-screen version text say `PYGAME 2.6.1` instead of `PYGAME-CE`.

Boot order becomes: **credits (≈5.6 s) → PONG PRO splash (2.2 s) → menu**.
A click (or key) skips **only the screen it is on**.

## Architecture

One new class-per-screen module, matching the established convention:

- **New** `src/pongpro/scenes/credits.py` → `CreditsScene(Scene)`. Draws the
  starfield/vignette backdrop via the shared `draw_backdrop`, animates two
  pieces of text, and `stack.replace(SplashScene(), transition=Transition.FADE)`
  when its timer expires or the user skips. The import of `SplashScene` is
  **deferred into the method body** (same trick `splash.py:43` uses for
  `MenuScene`) to avoid a circular import.
- **Edit** `src/pongpro/app.py:122` → boot `CreditsScene()` instead of
  `SplashScene()`. `SplashScene` itself is untouched except the one version
  string on line 80 — its "defer audio init to the second frame" boot trick
  must keep working exactly as before.
- **Ripple:** every test/tool that boots the real `Application` and counts
  frames to reach the menu now needs ≈5.6 s (≈672 frames @ 120 Hz) more:
  `tests/test_layout.py:116`, `tools/shots.py`, `tools/smoke_run.py`.
  `tools/check_imports.py` needs the new module in its `MODULES` list.

## Tech Stack

Python 3.12, pygame 2.6.1, no new dependencies, no binary assets. All motion is
closed-form functions of `self._t` (no per-frame mutable animation state), so a
test can jump to any time by stepping frames.

## Spec (the decisions the implementer must honour)

**Copy — exactly two lines, nothing else readable on screen:**

- `GAME CREATOR` — small label, wide letterspacing, `Color.TEXT_DIM`
- `ASHIRYA WILSON D'SOUZA` — the name, `Color.TEXT`, accent-cycled glow

All-caps, to match `PONG PRO` / `PRODUCTION EDITION` / `FOCUS`. No AI credit
line. No AI product named anywhere.

**Timeline (module constants, seconds):**

| Beat | Window | What happens |
| --- | --- | --- |
| 1 | 0.0–1.6 | Top rule draws outward from centre; `GAME CREATOR` fades up beneath it |
| 2 | 1.6–4.0 | Name resolves letter-by-letter (rise + fade); one left→right light sweep + glow bloom when the last letter lands |
| 3 | 4.0–5.6 | Second rule draws below the name; **hold perfectly still ≈1.6 s**; then fade + drift up into the splash |

Total `CREDITS_SECONDS = 5.6`. Persistent: drifting particle field, cycling
accent colour, thin progress line at the bottom, pulsing
`CLICK ANYWHERE TO SKIP` (blinks on a 0.5 s square wave, like
`splash.py:90`).

**Input:** any `MOUSEBUTTONDOWN` or `KEYDOWN` → skip, guarded by
`if self.stack is not None and not self.stack.transitioning:` — the stack
swallows `KEYDOWN` during fades but **not** mouse clicks, so without the guard
a click during the fade-out double-fires.

**Hand-off:** `self.stack.replace(SplashScene(), transition=Transition.FADE)`
— the same `replace` + `FADE` that `SplashScene._advance` uses for the menu.

**Layout:** name centred at `LOGICAL_W // 2` (1280), vertical centre of screen
roughly y=360; label above it; rules ≈340 px wide, thinner than the splash's
360 px progress bar. Name must fit inside `LOGICAL_W - 160`.

**Splash fix:** `splash.py:80`
`f"v{__version__}  ·  PYTHON 3.12  ·  PYGAME-CE"` →
`f"v{__version__}  ·  PYTHON 3.12  ·  PYGAME 2.6.1"`.

## Global Constraints

- Headless-safe: tests run with `SDL_VIDEODRIVER=dummy`,
  `SDL_AUDIODRIVER=dummy`, scratch `LOCALAPPDATA`; no display or audio device.
- No new dependencies, no binary assets, no AI product names, no network.
- Keep changes minimal and in the project's existing style (type hints,
  module docstring explaining *why*, no commented-out code).
- `--skip-splash` must still boot straight to the menu (it now skips credits
  too — `__main__.py` pushes `MenuScene`, which needs no change).
- Do not touch `SplashScene`'s second-frame audio-deferral logic.
- Shell quirks on this machine: quoted paths fail; use `python -c` sparingly
  (write a temp script under `%TEMP%\opencode` instead); commit with
  `git commit -F <path>`.

## Tasks

### 1. Bump the boot-frame assumptions and add failing credits tests (TDD)

**Files:** `tests/test_layout.py`

- `setUpModule` line 116: `_advance(400)  # splash -> menu` →
  `_advance(1100)  # credits -> splash -> menu`. 1100 frames ≈ 9.2 s covers
  5.6 s credits + 2.2 s splash + both ~0.25 s fades with margin.
- Add imports: `from pongpro.scenes.credits import CreditsScene`.
- Add tests in the existing `SceneLayoutTests` style, using the `_pushed`
  context manager and the module `_app`:
  1. `test_credits_draws` — push `CreditsScene()`, `_advance` a few frames,
     draw to `_app.frame`, assert no exception (mirror
     `test_menu_draws`).
  2. `test_credits_text_fits` — render both copy lines at their scene sizes
     via `_app.fonts.render(...)` and assert each width
     `< LOGICAL_W - 160` (mirror the existing content-fits tests).
  3. `test_credits_click_advances_to_splash` — push the scene, post
     `pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": (0, 0)})`
     through `_app.step_frame`, `_advance(40)` for the fade, and assert
     `isinstance(_app.stack.current, SplashScene)`.
  4. `test_credits_advances_on_timer` — push, `_advance(760)` (5.6 s + fade),
     assert the current scene is a `SplashScene`.
  5. `test_splash_version_string_says_pygame` — a text-regression guard on
     the literal: read the `splash.py` source via
     `Path(splash_mod.__file__).read_text(encoding="utf-8")` and assert
     `"PYGAME-CE" not in text` and `"PYGAME 2.6.1" in text`. Pinning the
     literal directly is the honest test here — rendering the surface and
     scanning pixels would be theatre.
- Run `python -m unittest tests.test_layout -v` — the new tests must **fail**
  (module `pongpro.scenes.credits` missing; splash string still wrong).

**Verify:** failures are exactly the expected ones (ImportError / assertion),
no unrelated breakage.

### 2. Implement `CreditsScene`

**Files:** `src/pongpro/scenes/credits.py` (new)

Module docstring must explain *why* the scene exists (credits the creator
before the brand splash; plays every launch by the creator's choice) and that
it hands off to `SplashScene`.

Constants:

```python
CREDITS_SECONDS = 5.6
LABEL = "GAME CREATOR"
NAME = "ASHIRYA WILSON D'SOUZA"
LABEL_START, NAME_START, RULE2_START = 0.2, 1.6, 4.0
LETTER_STAGGER, LETTER_DURATION = 0.07, 0.35
SWEEP_AT = 3.6
RULE_W, RULE_H = 340, 2
```

Class skeleton (mirrors `SplashScene`):

```python
class CreditsScene(Scene):
    opaque = True

    def __init__(self) -> None:
        super().__init__()
        self._t = 0.0

    def on_enter(self, **kwargs) -> None:
        self._t = 0.0

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
            self._skip()

    def _skip(self) -> None:
        if self.stack is None or self.stack.transitioning:
            return
        from .splash import SplashScene
        self.stack.replace(SplashScene(), transition=Transition.FADE)

    def update(self, dt: float) -> None:
        self._t += dt
        if self._t >= CREDITS_SECONDS:
            self._skip()

    def draw(self, surface: pygame.Surface) -> None: ...
```

`draw` details:

- `draw_backdrop(surface, self._t, seed=21, vignette=90)` — a **different
  seed** from the splash's 7 so the two boot screens don't look identical.
- Local easing helper `_ease_out_cubic(p) = 1 - (1 - p) ** 3` with `p`
  clamped to `[0, 1]` via a `_clamp01` helper.
- **Top rule:** width grows from the centre: `w = int(RULE_W * _ease_out_cubic(t / 1.2))`,
  drawn as two `pygame.draw.line` calls or one `Rect` centred on
  `LOGICAL_W // 2`; colour `Color.blend(Color.LINE, accent, 0.5)`.
- **Label:** alpha/scale from `_ease_out_cubic((t - LABEL_START) / 0.8)`,
  rendered once per frame with
  `ctx.fonts.render(LABEL, 22, Color.TEXT_DIM, bold=True)`, blitted centred
  below the rule. Use `set_alpha` on a per-frame surface (the font cache
  returns shared surfaces — **convert to a copy first**:
  `surf.copy().set_alpha(...)` — never mutate a cached surface).
- **Name, letter by letter:** iterate `enumerate(NAME)`; each letter's
  progress is `p = _ease_out_cubic((t - NAME_START - i * LETTER_STAGGER) / LETTER_DURATION)`;
  render each glyph with `ctx.fonts.render(ch, 64, color, bold=True)`,
  accumulate x by `glyph.get_width() + 2` (letterspacing), blit at
  `y + int((1 - p) * 18)` with `set_alpha(int(255 * p))`. Spaces advance x
  without rendering. Colour cycles `Color.blend(Color.P1, Color.P2, 0.5 + 0.5 * math.sin(t * 1.7))`
  like the splash wordmark.
- **Sweep:** from `SWEEP_AT` for 0.7 s, a soft vertical band
  (`SRCALPHA` surface, gradient alpha) travels left→right across the name's
  bounding rect and is blitted with `BLEND_RGB_ADD`. Compute the name rect
  once by summing glyph widths (store it during the letter loop).
- **Glow bloom:** after the sweep, a radially faded ellipse behind the name
  whose alpha peaks and settles — build the glow surface once at first use and
  cache it on `self` (`self._glow`), only `set_alpha` per frame.
- **Bottom rule (beat 3):** same draw-from-centre animation starting at
  `RULE2_START`, below the name.
- **Hold:** beats 3's animations complete before 4.0 s, so nothing moves
  between then and 5.6 s — do not add idle motion there.
- **Progress line:** identical pattern to `splash.py:83-88` — 360×6 rounded
  rect at y=660, fill `min(1.0, t / CREDITS_SECONDS)`.
- **Skip hint:** `CLICK ANYWHERE TO SKIP`, 14 px, `Color.TEXT_DIM`, blinking
  `int(t * 2.4) % 2 == 0` at y≈690 — note the user asked for *click*, so the
  hint says click, unlike the splash's "press any key".
- **Exit drift:** from 4.8 s to 5.6 s, translate all credit content upward by
  `int(_ease_out_cubic((t - 4.8) / 0.8) * 40)` and fade its alpha down, so the
  fade transition doesn't cut a fully opaque screen.

**Verify:** `python -m unittest tests.test_layout -v` → all five new tests
pass.

### 3. Wire boot and fix the splash string

**Files:** `src/pongpro/app.py`, `src/pongpro\scenes\splash.py`

- `app.py`: add `from .scenes.credits import CreditsScene`; change line 122 to
  `self.stack.push(CreditsScene(), transition=Transition.NONE)`. Remove the
  now-unused `SplashScene` import if nothing else in `app.py` references it.
- `splash.py:80`: `"PYGAME-CE"` → `"PYGAME 2.6.1"`.

**Verify:** `python -m unittest discover -s tests -t .` → all **455 + new**
tests pass.

### 4. Update the tools that assume boot timing

**Files:** `tools/check_imports.py`, `tools/shots.py`, `tools/smoke_run.py`

- `check_imports.py`: add `"pongpro.scenes.credits"` to `MODULES` (after
  `"pongpro.scenes.common"`, keeping scene grouping). 46 → 47 modules.
- `shots.py`: add a credits shot. Follow the existing splash-style shot: boot
  the app, advance to the credits, step to a representative frame (~4.5 s, so
  both rules and the full name are visible), `shot(app, "credits")`. Bump any
  `run(300)  # splash -> menu` frame count to `run(1100)`.
- `smoke_run.py`: bump `run(300, "splash")` to a count that reaches the splash
  through the credits (`run(1100, "splash")` or whatever constant the file
  uses).

**Verify:**
- `python tools\check_imports.py` → `all 47 modules imported`
- `python tools\smoke_run.py` → all checks pass
- `python tools\shots.py` → 24 screenshots including `credits.png`

### 5. Update the README

**Files:** `README.md`

- The "Checking" table: `46` → `47` modules, `23` → `24` screens.
- Add `credits` to the `scenes/` line of the folder map.
- One plain sentence wherever the boot sequence is described, e.g. the
  controls/boot notes: the game opens with a credits screen, then the PONG
  PRO intro; clicking skips the current one.

**Verify:** grep README for `46`, `23 screens` — stale numbers gone.

### 6. Real-boot verification

Run, in order, and inspect output:

1. `python tools\check_exe.py` (headless boot proof)
2. `python tools\check_exe.py --real` (real display + audio; must reach
   `MenuScene`)
3. `python tools\trace_missing.py` → `missing: 0`

If `check_exe.py` asserts a scene type after N frames, bump its frame count
the same way as the others.

### 7. Commit

Single commit on `main` (user chose normal commits, no history rewrite).
Write the message to `%TEMP%\opencode\pongpro_msg6.txt` and
`git commit -F` it, covering: new credits screen, boot order change, splash
version-string fix, tool/test frame-count bumps. Then `git push origin main`.

Files to stage: `src/pongpro/scenes/credits.py`, `src/pongpro/app.py`,
`src/pongpro/scenes/splash.py`, `tests/test_layout.py`,
`tools/check_imports.py`, `tools/shots.py`, `tools/smoke_run.py`,
`README.md`, plus the spec and plan docs under `docs/superpowers/`.

## Review Focus

- **`stack.transitioning` guard** in `_skip` — the double-fire hazard is real
  (stack swallows KEYDOWN during fades but not mouse clicks).
- **Cached font surfaces must not be mutated** — `fonts.render` returns LRU-
  cached surfaces; always `.copy()` before `set_alpha`.
- **`SplashScene`'s second-frame audio deferral is intact** — the hand-off must
  `replace` (not push) a fresh `SplashScene()`, and `app.py` must no longer
  import it if unused.
- **The 1.6 s still hold** — verify no idle animation creeps in between 4.0 s
  and 5.6 s.
- **Frame-count bumps are consistent** — every place that boots the app and
  counts frames (`test_layout`, `shots`, `smoke_run`, possibly `check_exe`)
  must agree with `CREDITS_SECONDS + SPLASH_SECONDS + fades`.
- **No AI product named anywhere** in code, comments, docs, or commit message.
