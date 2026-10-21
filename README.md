# PongPro

A production-grade Pong for Windows 10, built on **Python 3.12** and
**pygame 2.6**. No binary assets: every sound effect, the music loop, and all
visuals are generated at runtime.

## Highlights

- **Deterministic fixed-timestep simulation** (120 Hz physics) with render
  interpolation, a frame-time clamp and a sub-step cap, so a hitch can never
  cause a spiral of death.
- **Scene state machine** — splash → menu → match → pause → results → replay,
  with fade transitions and a typed event bus decoupling gameplay from
  presentation.
- **Human-feeling AI** — predictive intercept (wall reflections included),
  per-difficulty reaction delay, gaussian aim error, deliberate whiffs and
  speed caps. Fully reproducible from its seed. The ladder is *measured*, not
  asserted: `tests\test_ai.py` runs full physics against a partner that never
  misses and pins how often each level lets the ball past — at least 62% /
  82% / 92% / 96% of arrivals returned for EASY → ELITE, with EASY held under
  90% so it stays beatable. Whiffs only ever cost one observation interval,
  so no difficulty can stand and watch a ball arrive.
- **Procedural audio** — paddle blips that rise in pitch as the rally grows,
  a goal fanfare, UI clicks and an 8-second music loop, all synthesised with
  NumPy.
- **Replay** — the last match is recorded as compact integer snapshots and can
  be watched back from the results screen.
- **Coins & shop** — a match pays out into a coin wallet; the shop spends them
  on cosmetics (balls, paddles, backgrounds, trails, hit effects) and
  gameplay-altering **powerups** (giant paddle, magnet, fire ball, shield,
  gold rush, freeze ray, shrink ray, reverser, slow field).
- **Robust persistence** — versioned JSON in `%LOCALAPPDATA%\PongPro`, atomic
  writes, corruption quarantine and migration hooks. The wallet lives in its
  own `shop.json` so an older build can never destroy purchases. The first run
  over a v1 profile also corrects a counter the old build doubled on every
  match: lifetime *returns* restart from zero, while wins, losses, playtime,
  longest rally and the per-difficulty table are carried over untouched.

## Running from source

```bat
python -m pip install -e .
python main.py
```

`main.py` works straight from a checkout (it adds `src/` to `sys.path`);
`pip install -e .` is recommended for day-to-day development.

Useful flags (via `python -m pongpro`): `--skip-splash`, `--frames N`
(headless-friendly CI smoke run), `--quiet`.

## Controls

| Action | Keys |
| --- | --- |
| Player 1 paddle | `W` / `S` (or `↑` / `↓`) |
| Player 2 paddle (2-player mode) | `↑` / `↓` |
| Left paddle (FOCUS mode) | `W` / `S` |
| Right paddle (FOCUS mode) | `I` / `K` **or** `↑` / `↓` |
| Fire powerup (P1) | `Space` |
| Fire powerup (P2 / right paddle) | `Enter` or `Keypad Enter` |
| Pause / back | `Esc` or `P` |
| Menu navigation | `↑` `↓` `←` `→`, `Enter`, mouse |
| Show the in-game controls card | `H` (from the menu) |
| Pick a mode straight from the menu | `1` 1P · `2` 2P · `3` AI vs AI · `4` Focus Mode |
| Open shop (from menu) | `F3` |
| Settings (from menu) | `F4` |
| AI debug overlay (in match) | `F2` |

## Modes

| Mode | What it is |
| --- | --- |
| **1 Player · vs AI** | Standard match against the bot ladder (EASY → ELITE). |
| **2 Players · Local** | Shared-keyboard duel. |
| **Focus Mode** | The brain-exercise mode: one player drives **both** paddles and keeps the ball off *both* goal lines. See below. |
| **AI vs AI** | Spectate two bots. |

### Focus

Focus inverts what the other three modes assume: there is no opponent, no
score, and no winner — only you against the ball.

- **One player, two paddles.** `W`/`S` drives the left, `I`/`K` *or*
  `↑`/`↓` drives the right. Both bindings work simultaneously.
- **Lives replace points.** The *First to N* rule you pick in the menu becomes
  your starting life count instead of a points target, and the run ends when
  the last one is spent.
- **Powerups are off** in this mode, so none of the shop's powerups appear as
  pickups. Everything cosmetic still applies — your equipped ball, trail, paddle
  and background are all used, and your total returns still count.
- **One pickup: the Life Orb.** A gold orb grants `+1` life, capped at the
  count you started the run with; at full health it pays bonus coins instead.
  It is deliberately **not sold in the shop** — it is FOCUS's own pickup and
  nothing else.
- **Speed still climbs** every return, exactly as in a duel. Losing a life
  resets it part-way (to 70%) but never below the opening serve, so a quick
  mistake can't make the run easier than its own first ball.
- **Your best run is kept.** Longest survival time and most returns are stored
  in your profile and shown on the menu.

The first time you enter Focus, a one-page explainer opens with the rules; it
offers a **don't show again** toggle and never reappears once dismissed.


In the shop: `↑` `↓` move (tabs → items → BACK), `←` `→` switch category,
`Enter` buys or equips, `Esc` leaves. The list shows a seven-row viewport and
**scrolls** through the whole category with the mouse wheel (or the arrow keys,
which pull the highlighted row back into view), so there is no page key to
learn. A scrollbar sits in the gutter beside the list, and a status line under
it reads e.g. `SHOWING 4-10 OF 10`. The mouse hovers and clicks too.

## Coins, the shop and powerups

Every match pays a reward built from a participation bonus, points scored,
the longest rally and the number of returns, plus a win bonus where it
applies (solo wins, any completed local versus match; never a spectated
AI-vs-AI game). Solo awards scale with difficulty. Gold Rush pays coins live
during the match and the results screen reports both figures.

`STARTING_COINS` is 250, enough for a couple of early purchases. The catalog
holds 53 items; the free "classic" skin of each category plus two free
powerups (No Powerup and Overdrive) are owned from the start.

A powerup is held **per paddle**. A human always gets the profile's equipped
powerup, but a bot instead draws one at random from the profile's *own
collection*: in 1P-vs-AI only the machine draws, and in AI-vs-AI both bots do.
The draw is independent of what you equipped, so the opponent never simply
mirrors your choice — it can coincide, but only by luck. Two-player still
shares one equipped spec, keeping that duel symmetric. Firing is manual
(`Space` / `Enter`); bots fire on their own reaction-like delay.

**Pickup bubbles.** A few seconds into a rally a random powerup drifts onto
the court as a glowing orb. It pays out to whichever paddle *last returned*
the ball: the ball has to have bounced off a paddle first, so a serve floats
straight through and nobody scores it. The collector gets that powerup running
for its own default duration **without losing the one it was holding** —
grabbing a pickup never costs you your special move. If nobody takes it within
its lifetime (30 s) it vanishes, and a fresh random one arrives 3–7 s later.

Only one effect of each kind can run on a paddle at a time, so every modifier
stays idempotent and can never stack; different kinds compose normally.

REVERSER treats the two sides differently on purpose. A human keeps full,
perfectly negated control — that *is* the punishment, they have to re-map
their own hands under pressure. A bot gets no clean mirror: it keeps
computing the right intercept but mis-reads its own inputs in bursts, mostly
wrong and occasionally right, so it overshoots and half-recovers like a
disoriented player. Measured against a HARD bot that reads 100% of rallies,
that lands at about a 27% return rate — up from 10%, which was so heavy the bot
never contested a rally at all. Still a heavy debuff, but never the guaranteed
free point a full negation used to hand over, and never so one-sided that the
powerup plays the point for you.

## Development

```bat
python -m unittest discover -s tests -t .   :: 455 unit tests (layout + economy + powerups + bubbles + FOCUS mode + controls + AI behaviour + persistence)
python tools\check_imports.py               :: all 46 modules import headlessly
python tools\check_audio.py                 :: synth -> mixer round trip
python tools\smoke_run.py                   :: 36 end-to-end checks (shop, pickups, AI loadout)
python tools\shots.py                       :: renders all 23 screens to PNG
python tools\make_icon.py                   :: regenerates packaging\pongpro.ico
```

Headless runs need `SDL_VIDEODRIVER=dummy` and `SDL_AUDIODRIVER=dummy`.
`tools\shots.py` writes `tools\shots\*.png` so screen layout can be reviewed
without launching the game; `tests\test_layout.py` asserts programmatically
that no screen has overlapping or off-screen elements.

## Building a Windows release

```bat
tools\build_release.bat
```

Produces `dist\PongPro\PongPro.exe` (onedir, windowed). The spec is
`pongpro.spec`; onedir is used instead of onefile for fast startup and to
avoid antivirus false positives.

The window and taskbar icon is generated, not shipped: it is drawn by
`rendering/icon.py` and written to `packaging\pongpro.ico` by
`tools\make_icon.py`, which `pongpro.spec` picks up. Run that tool once
before building if the file is missing. At runtime the same renderer supplies
the window icon, so the two can never drift apart.

## Project layout

```
main.py              source-checkout launcher (DPI aware)
pongpro.spec         PyInstaller build spec
src/pongpro/
  app.py             application shell and frame loop
  core/              constants, settings, events, state machine, timestep
  audio/             NumPy synthesiser + mixer manager
  economy/           shop catalog (53 items) + wallet, rewards, ctx cache
  gameplay/          entities, physics, AI, match rules, FOCUS run, powerups, pickup bubbles, replay
  rendering/         camera, fonts, HUD, icon, particles, skins, UI toolkit, video
  scenes/            splash, menu, controls card, FOCUS explainer, shop, settings, gameplay, pause, results, replay
  storage/           atomic JSON documents, migration and quarantine
tests/               unit tests (no display or audio required)
tools/               import/audio checks, smoke harness, screenshots, icon, release build
```
