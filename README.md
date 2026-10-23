# PongPro

A Pong game for Windows — the classic game where you bounce a ball back and
forth and try to get it past your opponent.

It is written in **Python**, using a game library called **pygame**.

**There are no picture or sound files in this project.** The computer draws
every image and makes every sound while the game is running.

---

## ▶ How to play (the easy way)

You do **not** need to install anything.

1. Click the green **Code** button at the top of this page and choose
   **Download ZIP**.
2. Unzip the file and open the folder.
3. Open the **Builds** folder.
4. Double-click **PongPro.exe**.

The game starts. First you see a short **credits screen** naming the game's
creator, then the **PONG PRO** intro, then the menu. **Click anywhere** to
skip whichever of those two screens is playing.

### If Windows says "Windows protected your PC"

Windows shows this because the game was not made by a big company, so Windows
does not recognise it. **It is not a virus.**

Click **More info**, then **Run anyway**.

---

## 🎮 Controls

| What you want to do | Keys |
| --- | --- |
| Move your paddle (1 player) | `W` / `S`, or `↑` / `↓` |
| Move your paddle (player 2) | `↑` / `↓` |
| Left paddle in Focus Mode | `W` / `S` |
| Right paddle in Focus Mode | `I` / `K`, or `↑` / `↓` |
| Fire a powerup (player 1) | `Space` |
| Fire a powerup (player 2 / right paddle) | `Enter` or `Keypad Enter` |
| Pause the game, or go back a screen | `Esc` or `P` |
| Move around the menus | `↑` `↓` `←` `→`, `Enter`, or the mouse |
| Show the controls card while playing | `H` (from the menu) |
| Start a mode straight from the menu | `1` 1P · `2` 2P · `3` AI vs AI · `4` Focus |
| Open the shop (from the menu) | `F3` |
| Open settings (from the menu) | `F4` |
| Show the computer-player helper screen (for developers) | `F2` (during a match) |

---

## 🕹 The 4 game modes

| Mode | What happens |
| --- | --- |
| **1 Player · vs AI** | You play against the computer. It has 4 levels: EASY, NORMAL, HARD, ELITE. |
| **2 Players · Local** | Two people share one keyboard. |
| **Focus Mode** | *You* control **both** paddles. Keep the ball from getting past either side. |
| **AI vs AI** | You sit back and watch two computers play each other. |

### How good is the computer player?

We didn't just guess — we tested it. The game plays itself over and over, and
we counted how often each level manages to hit the ball back:

| Level | Hits the ball back |
| --- | --- |
| EASY | between 62% and 90% of the time (it misses a lot, so you can beat it) |
| NORMAL | at least 82% |
| HARD | at least 92% |
| ELITE | at least 96% (it almost never misses) |

The bots also hesitate, aim slightly wrong and occasionally miss on purpose,
so they feel like a person rather than a robot that never fails.

### Focus Mode, in simple words

Focus is different from the other three modes. There is no opponent, no score,
and no winner — it is just you against the ball.

- **You move two paddles.** `W`/`S` moves the left one. `I`/`K` (or `↑`/`↓`)
  moves the right one. Both sets of keys work at the same time.
- **You have lives instead of points.** The "First to N" number you choose in
  the menu becomes your number of lives. If the ball gets past both of your
  paddles you lose one life. When your lives reach 0, the run is over.
- **Powerups are turned off** in this mode, so nothing unfair floats onto the
  court.
- **One special pickup: the Life Orb.** It is a gold ball. Touch it and you get
  `+1` life. If you already have full lives, it gives you coins instead. You
  **cannot buy it in the shop** — you only find it inside Focus Mode.
- **The ball speeds up** every time you hit it back. Losing a life slows it
  down a little (to 70%), but never below the speed of the very first serve, so
  one mistake can't make the game easier.
- **Your best run is remembered.** Your longest survival time and your best
  number of returns are saved and shown on the menu.

The first time you open Focus Mode, a help page shows you the rules. It has a
**don't show again** tick box, so it won't bother you afterwards.

---

## 🪙 Coins, the shop and powerups

### How you earn coins

- Every match pays you coins when it ends.
- What you earn depends on: taking part, the points you scored, your longest
  rally (how many times you hit the ball in a row), and how many returns you
  made. There is a bonus for winning too.
- Beating a harder computer pays more.
- **Gold Rush** pays coins *while* the match is still going, and the results
  screen shows you both totals.

You start the game with **250 coins**. The shop has **53 things** to buy.

The free "classic" look of each category, plus two powerups (**No Powerup**
and **Overdrive**), are yours from the beginning.

### What you can buy

- **Looks** — different balls, paddles, backgrounds, trails and hit effects.
  These only change how the game looks.
- **Powerups** — special moves you can fire during a match.

### Moving around the shop

- `↑` `↓` move up and down the list
- `←` `→` change the category
- `Enter` buys or selects the highlighted item
- `Esc` leaves the shop
- The **mouse wheel** scrolls down the list, so there is no page key to learn
- You can also click things with the mouse

The list shows 7 items at a time. A little bar (a scrollbar) sits beside it,
and the line underneath tells you where you are, for example
`SHOWING 4-10 OF 10`.

### How powerups work

- Every paddle holds **its own** powerup.
- You always use the one you chose. The **computer picks one at random from
  your own collection**, so it does not simply copy your choice.
  - In 1 Player mode only the computer draws one.
  - In AI vs AI mode both computers draw one.
  - In 2 Players mode both people share the same chosen powerup, so the duel
    stays fair.
- **You fire it yourself** with `Space` (or `Enter` for player 2). The computer
  waits a moment before firing.

### Pickup bubbles

- A few seconds into a rally, a glowing powerup ball drifts onto the court.
- It goes to whichever paddle **hit the ball last**. The ball has to have
  bounced off a paddle first — a serve that just floats through gives nobody
  anything.
- Grabbing it does **not** throw away the powerup you were holding. You keep
  both.
- If nobody picks it up within **30 seconds** it vanishes, and a fresh one
  arrives 3–7 seconds later.
- Two of the same effect never stack on top of each other. Different effects
  can work together normally.

### REVERSER (the confusing one)

REVERSER flips your controls left-to-right, so you have to re-learn your own
hands while under pressure.

For the computer player it is **not** a perfect flip: it keeps trying to work
out the right place to move, but reads its own inputs wrong in bursts, so it
overshoots and then corrects itself — like a player who is disoriented. It is
still a heavy penalty, but never a free point either way.

---

## 🖥 Running the game from the code

Only do this if you want to **change** the game. To just play it, use
`Builds\PongPro.exe` above.

### The easy way

Double-click **`run.bat`** in the main project folder. It will:

1. Look for Python on your computer.
2. Download **pygame** and **numpy** if they are missing (needs internet the
   first time).
3. Start the game.

### The manual way

Open a command prompt in the project folder and type these two lines, one at a
time:

```
python -m pip install -e .
python main.py
```

- The first line installs the game's parts.
- The second line starts the game.

**You need:** Python 3.11 or newer. The game was built with Python 3.12.

Some handy options (use them with `python -m pongpro`):

- `--skip-splash` — skip the credits and the intro screen
- `--frames N` — run N frames then stop (useful for testing)
- `--quiet` — less text in the window

---

## 🔨 Making your own copy of the game

Changed the code and want a new `PongPro.exe`? Run this from the project
folder:

```
tools\build_release.bat
```

It takes about a minute. The new game appears at `dist\PongPro.exe` and is
copied to `Builds\PongPro.exe`.

What happens behind the scenes, in plain words:

- A tool called **PyInstaller** packs the game, Python, pygame and numpy all
  into **one single file**.
- The result runs on any Windows computer with nothing to install.
- A **safety check** then makes sure that file is complete before it is used.
  (An early version of the game was missing some important parts, so every
  build is now checked automatically.)

A couple of notes:

- The window's icon is drawn by the game itself. `tools\make_icon.py` creates
  the file `packaging\pongpro.ico`, which the build uses.
- Because the `.exe` is not signed by a company, antivirus software may
  sometimes warn you. That is normal for games built this way.

---

## ✅ Checking that everything still works

| Command | What it checks |
| --- | --- |
| `python -m unittest discover -s tests -t .` | Runs all **461** tests |
| `python tools\check_imports.py` | All **47** parts of the game can load |
| `python tools\check_audio.py` | Sounds are made and played correctly |
| `python tools\smoke_run.py` | **36** end-to-end checks (shop, pickups, computer player) |
| `python tools\shots.py` | Saves a picture of all **24** screens |
| `python tools\make_icon.py` | Makes the icon file again |
| `python tools\check_exe.py` | Starts the `.exe` and proves it really runs |
| `python tools\trace_missing.py` | Confirms git has every file the game needs |

Most of these do not open a window, so you can run them on any computer.

Two useful ones to know about:

- `python tools\check_exe.py --real` uses the real screen and sound device
  instead of a pretend one.
- `python tools\cleanup.py` lists temporary files you can safely delete. Add
  `--apply` to actually delete them.

---

## 📁 What is inside the project folder

```
main.py              starts the game straight from the code
run.bat              double-click this: installs what's needed, then plays
pongpro.spec         the recipe PyInstaller follows to build the .exe
Builds/PongPro.exe   the finished game — just double-click it
src/pongpro/
  app.py             the main game loop (the engine that keeps everything running)
  core/              settings, keyboard events, screen changing, timing
  audio/             makes all the sounds and music with maths
  economy/           the shop items (53) and your coin wallet
  gameplay/          the paddles, ball, computer player, rules, powerups, replay
  rendering/         drawing: camera, fonts, scores, icon, effects, colours, menu look
  scenes/            each screen: credits, splash, menu, controls, shop, settings, match, pause, results, replay
  storage/           saves your progress safely on your computer
tests/               the 461 tests (none of them need a screen or speakers)
tools/               helper scripts: checks, screenshots, icon, building, cleanup
```

Your saved game lives in `C:\Users\<you>\AppData\Local\PongPro` on Windows.
It is stored as readable JSON text files, and it is written safely so a crash
can never destroy your coins.

---

## 📖 Words used in this guide

| Word | Meaning |
| --- | --- |
| **Python** | The programming language the game is written in. |
| **pygame** | A Python add-on (a *library*) used to make games. |
| **numpy** | A Python add-on for fast maths — the game uses it to create sounds. |
| **`.exe`** | A program file you can double-click on Windows. |
| **AI** | The computer player (short for *artificial intelligence*). |
| **rally** | The ball being hit back and forth many times in a row. |
| **return** | Successfully hitting the ball back. |
| **powerup** | A special move you can fire during a match. |
| **repository / repo** | This project's home on GitHub. |
| **build** | Turning the code into a `.exe` you can double-click. |
