"""
Bomb Defusal prototype (single file).

A 3x3 grid: the centre tile is the countdown timer, the other eight tiles are
puzzle modules. Each board draws unique puzzle types at random from PUZZLE_POOL;
any tiles left over are filled with placeholder switches (click to toggle).

Every module is live at all times; zoom in to see and work it more comfortably.

Controls
    left click     use a module (click tiles, drag wires, press buttons)
    scroll wheel   zoom in / out around the cursor
    drag           pan: left-drag on any spot that isn't a control, or right/middle-drag anywhere
    keyboard       type answers in modules that ask for one (Enter submits)
    SPACE (hold)   show the rule book while held
    ESC            quit

Requires: pygame   (py -m pip install pygame)
"""

import itertools
import math
import os
import random
import sys

import pygame

# --- Tunables -----------------------------------------------------------------
FPS = 120
TIME_LIMIT_MS = 240_000         # countdown length
PENALTY_MS = 5_000              # time lost per mistake in modules that punish them
WIN_SCREEN_DELAY_MS = 2_000     # green timer shows this long before the congrats screen
WIN_ZOOM_OUT_MS = 900           # camera eases back to the whole bomb at the start of that wait
BOOK_ANIM_MS = 320              # rule book slide in / out
BOOK_FONT_SIZES = (20, 18, 16, 14)  # rule book text sizes, largest that fits wins

GRID_FRAC = 0.75                # grid side as a fraction of the screen's shorter side
TILE_GAP = 14
ZOOM_STEP = 1.15                # zoom factor per scroll notch
MAX_TILE_FRAC = 0.92            # max zoom: one tile fills this much of the screen's shorter side
MODULE_DESIGN = 640             # module size that the pixel constants in draw code are tuned for

BG = (24, 26, 33)
PANEL = (36, 39, 48)
TILE_OFF = (58, 62, 76)
TILE_OFF_HOVER = (72, 77, 94)
TILE_ON = (70, 170, 110)
TILE_ON_HOVER = (85, 190, 125)
SOLVED_BG = (34, 60, 46)
TIMER_TILE = (16, 17, 22)
TIMER_RUNNING = (235, 70, 60)
TIMER_DONE = (90, 220, 130)
TEXT = (230, 232, 238)
DIM = (140, 145, 160)
BUTTON = (70, 120, 220)
BUTTON_HOVER = (90, 140, 240)
BOOK_PAGE = (232, 224, 204)
BOOK_INK = (40, 36, 30)
BOOK_ACCENT = (150, 50, 40)

CENTER = 4                      # index of the timer tile in the 3x3 grid
POSITION_NAMES = ["top-left", "top", "top-right", "left", "centre",
                  "right", "bottom-left", "bottom", "bottom-right"]


def wrap_text(font, text, width):
    words = text.split()
    lines, line = [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if font.size(trial)[0] <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def scale_of(rect):
    """How big this on-screen module is relative to MODULE_DESIGN."""
    return rect.w / MODULE_DESIGN


def draw_button(surface, rect, label, font, hover):
    pygame.draw.rect(surface, BUTTON_HOVER if hover else BUTTON, rect,
                     border_radius=max(2, rect.h // 6))
    img = font.render(label, True, TEXT)
    surface.blit(img, img.get_rect(center=rect.center))


def draw_module_frame(surface, rect, fonts, title, solved):
    s = scale_of(rect)
    radius = max(2, int(36 * s))
    pygame.draw.rect(surface, SOLVED_BG if solved else TILE_OFF, rect, border_radius=radius)
    if solved:
        pygame.draw.rect(surface, TILE_ON, rect, max(1, int(10 * s)), border_radius=radius)
    if title:
        img = fonts["main"].render(title, True, DIM)
        surface.blit(img, img.get_rect(midtop=(rect.centerx, rect.top + 14 * s)))


def reset_button_rect(rect):
    """Top-right corner button shared by modules that can be put back to their start."""
    s = scale_of(rect)
    return pygame.Rect(rect.right - 112 * s, rect.top + 12 * s, 98 * s, 40 * s)


def draw_status(surface, rect, fonts, msg, color):
    img = fonts["main"].render(msg, True, color)
    surface.blit(img, img.get_rect(midbottom=(rect.centerx, rect.bottom - 16 * scale_of(rect))))


# --- Puzzles --------------------------------------------------------------------
class Puzzle:
    """Base module. Modules are always live and drawn at whatever on-screen size
    `rect` has (geometry scales with rect; fonts arrive pre-scaled in `fonts`).

    on_mouse_down returns True when the press hit a control; otherwise the game
    treats the drag as a pan. `penalty_ms` is time owed since the game last
    collected it; the game takes it off the timer.
    """
    title = ""

    def __init__(self):
        self.solved = False
        self.solved_at = None
        self.penalty_ms = 0

    def mark_solved(self):
        self.solved = True
        self.solved_at = pygame.time.get_ticks()

    def update(self, now): pass
    def on_mouse_down(self, pos, rect, button): return False
    def on_mouse_up(self, pos, rect): pass
    def on_key(self, event): pass

    def draw(self, surface, rect, fonts, mouse):
        raise NotImplementedError

    def manual(self, position):
        """Rules specific to this board's instance, for the rule book."""
        return []

    @staticmethod
    def manual_general():
        """How this kind of module works, for the rule book."""
        return []


class SwitchPuzzle(Puzzle):
    """Placeholder module: click the tile to flip it on/off."""
    title = "Switch"

    def on_mouse_down(self, pos, rect, button):
        if button != 1 or not rect.collidepoint(pos):
            return False
        if self.solved:
            self.solved, self.solved_at = False, None
        else:
            self.mark_solved()
        return True

    def draw(self, surface, rect, fonts, mouse):
        hover = rect.collidepoint(mouse)
        if self.solved:
            color = TILE_ON_HOVER if hover else TILE_ON
        else:
            color = TILE_OFF_HOVER if hover else TILE_OFF
        pygame.draw.rect(surface, color, rect, border_radius=max(2, int(36 * scale_of(rect))))
        label = fonts["big"].render("ON" if self.solved else "Switch", True,
                                    TEXT if self.solved else DIM)
        surface.blit(label, label.get_rect(center=rect.center))

    @staticmethod
    def manual_general():
        return [("text", "Click each switch to turn it on.")]


# ---- 1. Wires ------------------------------------------------------------------
WIRE_COLORS = {
    "red": (220, 60, 60),
    "blue": (60, 115, 235),
    "green": (55, 175, 90),
    "yellow": (235, 200, 55),
    "white": (225, 225, 225),
}
WIRE_PATTERNS = ("solid", "striped")
STRIPE_INK = (22, 22, 28)
SOCKET = (14, 15, 19)
SOCKET_RIM = (110, 115, 130)


def wire_rule_holds(rule, slot):
    """slot[w] is the input index (0 = top) wire w is connected to."""
    kind = rule[0]
    if kind == "above":
        return slot[rule[1]] < slot[rule[2]]
    if kind == "directly_above":
        return slot[rule[1]] + 1 == slot[rule[2]]
    if kind == "next_to":
        return abs(slot[rule[1]] - slot[rule[2]]) == 1
    if kind == "not_next_to":
        return abs(slot[rule[1]] - slot[rule[2]]) != 1
    if kind == "between":
        lo, hi = sorted((slot[rule[1]], slot[rule[3]]))
        return lo < slot[rule[2]] < hi
    raise ValueError(kind)


def generate_wire_rules(n):
    """Pick a target wiring and a minimal set of relative rules that pins it down.

    One wire (the "hidden" wire) is never mentioned, so players must deduce it.
    Relative rules can't tell "everything shifted down one" apart, so the hidden
    wire always sits in an interior input, where the gap it leaves is detectable.
    """
    all_slots = list(itertools.permutations(range(n)))

    def solutions(rules):
        return [s for s in all_slots if all(wire_rule_holds(r, s) for r in rules)]

    while True:
        target = random.sample(range(n), n)          # target[wire] = input index
        hidden = random.choice([w for w in range(n) if 0 < target[w] < n - 1])
        others = [w for w in range(n) if w != hidden]

        candidates = []
        for a, b in itertools.permutations(others, 2):
            if target[a] < target[b]:
                candidates.append(("above", a, b))
            if target[a] + 1 == target[b]:
                candidates.append(("directly_above", a, b))
        for a, b in itertools.combinations(others, 2):
            near = abs(target[a] - target[b]) == 1
            candidates.append(("next_to" if near else "not_next_to", a, b))
        for trio in itertools.combinations(others, 3):
            lo, mid, hi = sorted(trio, key=lambda w: target[w])
            candidates.append(("between", lo, mid, hi))

        chosen, remaining = [], all_slots
        while len(remaining) > 1:
            useful = [r for r in candidates
                      if r not in chosen and any(not wire_rule_holds(r, s) for s in remaining)]
            if not useful:
                break
            rule = random.choice(useful)
            chosen.append(rule)
            remaining = [s for s in remaining if wire_rule_holds(rule, s)]
        if len(remaining) != 1:
            continue

        # Drop any rule the others already imply, so every rule matters.
        for rule in random.sample(chosen, len(chosen)):
            trial = [r for r in chosen if r is not rule]
            if len(solutions(trial)) == 1:
                chosen = trial
        random.shuffle(chosen)
        return target, chosen


class WirePuzzle(Puzzle):
    """Drag each wire from the left to an input on the right, as the rules dictate."""
    title = "Wires"

    def __init__(self):
        super().__init__()
        n = random.randint(4, 5)
        combos = [(c, p) for c in WIRE_COLORS for p in WIRE_PATTERNS]
        self.wires = random.sample(combos, n)        # left-hand order, top to bottom
        self.target, self.rules = generate_wire_rules(n)
        self.connections = [None] * n                # connections[wire] = input index
        self.dragging = None
        self.drag_origin = None
        self.wrong = False

    # ---- geometry ----
    def layout(self, rect):
        n = len(self.wires)
        pad = rect.h * 0.13
        step = (rect.h - 2 * pad) / (n - 1)
        ys = [rect.y + pad + i * step for i in range(n)]
        plug_w = rect.w * 0.13
        plug_h = min(rect.h * 0.075, step * 0.55)
        plug_x = rect.x + rect.w * 0.16
        socket_x = rect.right - rect.w * 0.16
        cable_w = max(2, int(plug_h * 0.32))
        return ys, plug_w, plug_h, plug_x, socket_x, cable_w

    def plug_rect(self, rect, w):
        ys, plug_w, plug_h, plug_x, _, _ = self.layout(rect)
        r = pygame.Rect(0, 0, plug_w, plug_h)
        r.center = (plug_x, ys[w])
        return r

    def socket_pos(self, rect, s):
        ys, _, _, _, socket_x, _ = self.layout(rect)
        return socket_x, ys[s]

    def socket_at(self, rect, pos):
        _, _, plug_h, _, _, _ = self.layout(rect)
        for s in range(len(self.wires)):
            sx, sy = self.socket_pos(rect, s)
            if (pos[0] - sx) ** 2 + (pos[1] - sy) ** 2 <= (plug_h * 0.9) ** 2:
                return s
        return None

    # ---- input ----
    def on_mouse_down(self, pos, rect, button):
        if self.solved or button != 1:
            return False
        for w in range(len(self.wires)):
            if self.plug_rect(rect, w).inflate(10, 10).collidepoint(pos):
                self.dragging = w
                break
        else:
            s = self.socket_at(rect, pos)
            if s is not None and s in self.connections:
                self.dragging = self.connections.index(s)
        if self.dragging is None:
            return False
        self.drag_origin = self.connections[self.dragging]     # input it came from, if any
        self.connections[self.dragging] = None
        self.wrong = False
        return True

    def on_mouse_up(self, pos, rect):
        if self.dragging is None:
            return
        w, self.dragging = self.dragging, None
        s = self.socket_at(rect, pos)
        if s is None:
            return
        if s in self.connections:
            # The wire already there takes the dragged wire's old input (swap);
            # a wire dragged fresh from its plug just bumps it out.
            self.connections[self.connections.index(s)] = self.drag_origin
        self.connections[w] = s
        if None not in self.connections:
            if self.connections == self.target:
                self.mark_solved()
            else:
                self.wrong = True

    # ---- drawing ----
    def draw_plug(self, surface, r, w):
        color, pattern = self.wires[w]
        pygame.draw.rect(surface, WIRE_COLORS[color], r, border_radius=4)
        if pattern == "striped":
            clip = surface.get_clip()
            surface.set_clip(r.clip(clip) if clip else r)
            step = max(6, r.h // 2)
            for x in range(r.left - r.h, r.right + r.h, step):
                pygame.draw.line(surface, STRIPE_INK, (x, r.bottom), (x + r.h, r.top),
                                 max(2, step // 3))
            surface.set_clip(clip)
        pygame.draw.rect(surface, STRIPE_INK, r, 2, border_radius=4)

    def draw_cable(self, surface, start, end, w, width):
        color, pattern = self.wires[w]
        dx = end[0] - start[0]
        c1 = (start[0] + dx * 0.45, start[1])
        c2 = (end[0] - dx * 0.45, end[1])
        pts = []
        for i in range(33):
            t = i / 32
            u = 1 - t
            pts.append((u ** 3 * start[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t ** 3 * end[0],
                        u ** 3 * start[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t ** 3 * end[1]))
        band = width * 1.6
        travelled = 0.0
        for a, b in zip(pts, pts[1:]):
            seg = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
            striped_here = pattern == "striped" and int(travelled / band) % 2 == 1
            ink = STRIPE_INK if striped_here else WIRE_COLORS[color]
            pygame.draw.line(surface, ink, a, b, width)
            pygame.draw.circle(surface, ink, b, width / 2)
            travelled += seg
        pygame.draw.circle(surface, WIRE_COLORS[color], end, width * 0.9)
        pygame.draw.circle(surface, STRIPE_INK, end, width * 0.9, 1)

    def draw(self, surface, rect, fonts, mouse):
        draw_module_frame(surface, rect, fonts, "WIRES", self.solved)

        ys, plug_w, plug_h, plug_x, socket_x, cable_w = self.layout(rect)
        for s in range(len(self.wires)):
            pos = self.socket_pos(rect, s)
            pygame.draw.circle(surface, SOCKET, pos, plug_h * 0.6)
            pygame.draw.circle(surface, SOCKET_RIM, pos, plug_h * 0.6, 2)

        for w in range(len(self.wires)):
            pr = self.plug_rect(rect, w)
            start = (pr.right, pr.centery)
            if self.connections[w] is not None:
                self.draw_cable(surface, start, self.socket_pos(rect, self.connections[w]), w, cable_w)
            elif self.dragging == w:
                self.draw_cable(surface, start, mouse, w, cable_w)
            self.draw_plug(surface, pr, w)

        if self.solved:
            draw_status(surface, rect, fonts, "SOLVED", TIMER_DONE)
        elif self.wrong:
            draw_status(surface, rect, fonts, "Incorrect wiring - check the rule book", TIMER_RUNNING)
        else:
            draw_status(surface, rect, fonts, "Drag every wire to an input", DIM)

    def manual(self, position):
        def name(w):
            color, pattern = self.wires[w]
            return f"the {color} {pattern} wire"

        lines = []
        for rule in self.rules:
            kind = rule[0]
            if kind == "above":
                text = f"{name(rule[1])} connects somewhere above {name(rule[2])}."
            elif kind == "directly_above":
                text = f"{name(rule[1])} connects directly above {name(rule[2])}."
            elif kind == "next_to":
                text = f"{name(rule[1])} and {name(rule[2])} connect next to each other."
            elif kind == "not_next_to":
                text = f"{name(rule[1])} and {name(rule[2])} are not next to each other."
            else:
                text = f"{name(rule[2])} connects somewhere between {name(rule[1])} and {name(rule[3])}."
            lines.append(("rule", text[0].upper() + text[1:]))
        return lines

    @staticmethod
    def manual_general():
        return [("text", "Drag each wire on the left to one input on the right. "
                         "Every wire must be connected. \"Above\" and \"next to\" refer to "
                         "the inputs. Not every wire has a rule - deduce the rest.")]


# ---- 2. Tango (binary logic grid with = / x clues) ---------------------------
BAL_N = 6
BAL_SYMBOLS = ((240, 150, 50), (70, 140, 230))     # 0 = orange circle, 1 = blue square
BAL_CELL = (80, 85, 102)
BAL_GIVEN = (48, 51, 62)
BAL_BAD = (235, 70, 60)
BAL_EXTRA_GIVENS = 5            # hints added on top of the minimal unique clue set
BAL_EXTRA_SIGNS = 3


def _no_triple(seq):
    return not any(seq[i] is not None and seq[i] == seq[i + 1] == seq[i + 2]
                   for i in range(len(seq) - 2))


BAL_ROWS = [p for p in itertools.product((0, 1), repeat=BAL_N)
            if sum(p) == BAL_N // 2 and _no_triple(p)]


def balance_solve(givens, signs, limit=2, shuffle=False):
    """Return up to `limit` full grids (tuples of row tuples) satisfying the clues.

    givens: {(r, c): value}; signs: [(same: bool, (r1, c1), (r2, c2))] for adjacent cells.
    """
    row_opts = []
    for r in range(BAL_N):
        opts = [p for p in BAL_ROWS
                if all(p[c] == v for (rr, c), v in givens.items() if rr == r)
                and all((p[a[1]] == p[b[1]]) == same
                        for same, a, b in signs if a[0] == b[0] == r)]
        if shuffle:
            random.shuffle(opts)
        row_opts.append(opts)
    vertical = [[(same, a[1]) for same, a, b in signs if a[1] == b[1] and max(a[0], b[0]) == r]
                for r in range(BAL_N)]
    half = BAL_N // 2
    found = []

    def fits(rows, p):
        r = len(rows)
        for c in range(BAL_N):
            col = [row[c] for row in rows] + [p[c]]
            ones = sum(col)
            if ones > half or len(col) - ones > half:
                return False
            if r >= 2 and col[-1] == col[-2] == col[-3]:
                return False
        return all((rows[-1][c] == p[c]) == same for same, c in vertical[r])

    def dfs(rows):
        if len(found) >= limit:
            return
        if len(rows) == BAL_N:
            found.append(tuple(rows))
            return
        for p in row_opts[len(rows)]:
            if fits(rows, p):
                dfs(rows + [p])

    dfs([])
    return found


def generate_balance():
    """Random full grid plus givens and =/x clues with exactly one solution: a minimal
    unique set, then BAL_EXTRA_GIVENS / BAL_EXTRA_SIGNS extra clues as hints."""
    solution = balance_solve({}, [], limit=1, shuffle=True)[0]
    cells = [(r, c) for r in range(BAL_N) for c in range(BAL_N)]
    edges = [((r, c), (r, c + 1)) for r in range(BAL_N) for c in range(BAL_N - 1)]
    edges += [((r, c), (r + 1, c)) for r in range(BAL_N - 1) for c in range(BAL_N)]
    candidates = [("g", cell) for cell in cells] + [("s", e) for e in edges]
    random.shuffle(candidates)

    def split(clues):
        givens = {cell: solution[cell[0]][cell[1]] for kind, cell in clues if kind == "g"}
        signs = [(solution[a[0]][a[1]] == solution[b[0]][b[1]], a, b)
                 for kind, (a, b) in ((k, v) for k, v in clues if k == "s")]
        return givens, signs

    def unique(clues):
        return len(balance_solve(*split(clues))) == 1

    chosen = []
    for cand in candidates:
        chosen.append(cand)
        if len(chosen) >= 6 and unique(chosen):
            break
    for cand in random.sample(chosen, len(chosen)):
        trial = [c for c in chosen if c is not cand]
        if unique(trial):
            chosen = trial
    # The minimal set is very hard; hand back some redundant clues as hints.
    unused = [c for c in candidates if c not in chosen]
    chosen += [c for c in unused if c[0] == "g"][:BAL_EXTRA_GIVENS]
    chosen += [c for c in unused if c[0] == "s"][:BAL_EXTRA_SIGNS]
    givens, signs = split(chosen)
    return solution, givens, signs


class TangoPuzzle(Puzzle):
    """6x6 grid of two symbols; balanced rows/columns, no three in a row, =/x clues."""
    title = "Tango"

    def __init__(self):
        super().__init__()
        self.solution, self.givens, self.signs = generate_balance()
        self.grid = [[self.givens.get((r, c)) for c in range(BAL_N)] for r in range(BAL_N)]

    def layout(self, rect):
        side = min(rect.w, rect.h) * 0.72
        cell = side / BAL_N
        x0 = rect.centerx - side / 2
        y0 = rect.centery - side / 2
        return x0, y0, cell

    def cell_rect(self, rect, r, c):
        x0, y0, cell = self.layout(rect)
        pad = max(1, cell * 0.05)
        return pygame.Rect(x0 + c * cell + pad, y0 + r * cell + pad, cell - 2 * pad, cell - 2 * pad)

    def violations(self):
        bad = set()
        lines = [[(r, c) for c in range(BAL_N)] for r in range(BAL_N)]
        lines += [[(r, c) for r in range(BAL_N)] for c in range(BAL_N)]
        for line in lines:
            vals = [self.grid[r][c] for r, c in line]
            for sym in (0, 1):
                if vals.count(sym) > BAL_N // 2:
                    bad.update(cell for cell, v in zip(line, vals) if v == sym)
            for i in range(BAL_N - 2):
                if vals[i] is not None and vals[i] == vals[i + 1] == vals[i + 2]:
                    bad.update(line[i:i + 3])
        for same, a, b in self.signs:
            va, vb = self.grid[a[0]][a[1]], self.grid[b[0]][b[1]]
            if va is not None and vb is not None and (va == vb) != same:
                bad.update((a, b))
        return bad

    def full(self):
        return all(v is not None for row in self.grid for v in row)

    def on_mouse_down(self, pos, rect, button):
        if button != 1:
            return False
        if reset_button_rect(rect).collidepoint(pos):
            if not self.solved:
                self.grid = [[self.givens.get((r, c)) for c in range(BAL_N)] for r in range(BAL_N)]
            return True
        for r in range(BAL_N):
            for c in range(BAL_N):
                if self.cell_rect(rect, r, c).collidepoint(pos):
                    if not self.solved and (r, c) not in self.givens:
                        v = self.grid[r][c]
                        self.grid[r][c] = 0 if v is None else (1 if v == 0 else None)
                        if tuple(map(tuple, self.grid)) == self.solution:
                            self.mark_solved()
                    return True
        return False

    def draw_symbol(self, surface, cr, v):
        if v == 0:
            pygame.draw.circle(surface, BAL_SYMBOLS[0], cr.center, cr.w * 0.32)
        else:
            sq = pygame.Rect(0, 0, cr.w * 0.56, cr.w * 0.56)
            sq.center = cr.center
            pygame.draw.rect(surface, BAL_SYMBOLS[1], sq, border_radius=max(2, int(cr.w * 0.08)))

    def draw(self, surface, rect, fonts, mouse):
        draw_module_frame(surface, rect, fonts, "TANGO", self.solved)
        if not self.solved:
            reset = reset_button_rect(rect)
            draw_button(surface, reset, "Reset", fonts["main"], reset.collidepoint(mouse))
        # Mistakes are only revealed once every cell has been filled in.
        bad = self.violations() if self.full() and not self.solved else set()
        for r in range(BAL_N):
            for c in range(BAL_N):
                cr = self.cell_rect(rect, r, c)
                hover = not self.solved and (r, c) not in self.givens and cr.collidepoint(mouse)
                bg = BAL_GIVEN if (r, c) in self.givens else (TILE_OFF_HOVER if hover else BAL_CELL)
                pygame.draw.rect(surface, bg, cr, border_radius=max(2, int(cr.w * 0.1)))
                if (r, c) in bad:
                    pygame.draw.rect(surface, BAL_BAD, cr, max(2, int(cr.w * 0.06)),
                                     border_radius=max(2, int(cr.w * 0.1)))
                if self.grid[r][c] is not None:
                    self.draw_symbol(surface, cr, self.grid[r][c])

        x0, y0, cell = self.layout(rect)
        for same, a, b in self.signs:
            cx = x0 + (a[1] + b[1] + 1) / 2 * cell
            cy = y0 + (a[0] + b[0] + 1) / 2 * cell
            rad = cell * 0.17
            pygame.draw.circle(surface, PANEL, (cx, cy), rad)
            k = rad * 0.5
            w = max(1, int(cell * 0.05))
            if same:
                pygame.draw.line(surface, TEXT, (cx - k, cy - k * 0.45), (cx + k, cy - k * 0.45), w)
                pygame.draw.line(surface, TEXT, (cx - k, cy + k * 0.45), (cx + k, cy + k * 0.45), w)
            else:
                pygame.draw.line(surface, TEXT, (cx - k, cy - k), (cx + k, cy + k), w)
                pygame.draw.line(surface, TEXT, (cx - k, cy + k), (cx + k, cy - k), w)

        if self.solved:
            draw_status(surface, rect, fonts, "SOLVED", TIMER_DONE)
        elif bad:
            draw_status(surface, rect, fonts, "Something breaks a rule", TIMER_RUNNING)
        else:
            draw_status(surface, rect, fonts, "Click a cell to cycle: circle, square, empty", DIM)

    @staticmethod
    def manual_general():
        return [("text", "Fill the grid with circles and squares. Every row and column holds "
                         "3 of each. No more than 2 of the same symbol may sit next to each "
                         "other in a row or column. Cells joined by = match; cells joined by x "
                         "differ. Dark cells are fixed. Reset clears your entries.")]


# ---- 3. Word memory ------------------------------------------------------------
WORD_POOL_TEXT = """
absent abroad absorb academy accent accept access account accuse achieve acquire across
action active actual adapt adjust admire admit adopt adult advance advice affair afford
afraid agency agenda airline airport alarm album alert alien alive allow almost alone
along alpha already altar amazing amber amount amuse anchor ancient anger angle angry
animal ankle annual answer anxiety anybody apart apology appeal appear apple apply approve
arena argue arise armchair armor around arrange arrest arrive arrow artist ashamed aside
asleep assist assume attach attack attempt attend attic attract auction audio author
autumn avenue avoid awake award aware awful backpack bacon badge balance balcony ballet
balloon bamboo banana bandage banjo banner barber bargain barrel basic basket battery
battle beach beacon beard beast beauty become bedroom beetle before begin behave behind
being belief bellow belong below bench beneath berry beside better beyond bicycle billion
biology biscuit bishop bitter blanket blast blend blind blink block blossom blouse board
boast bonus border borrow bottle bottom bounce boxer brain branch brave bread breeze brick
bride bridge brief bright bring broad broken bronze brook brother brown brush bubble bucket
budget buffalo build bullet bundle burden bureau burger butter button buyer cabbage cabin
cable cactus camel camera candle candy canoe canvas canyon carbon career cargo carpet
carrot carry cartoon castle casual catalog cattle cause cavern ceiling celery cellar
cement census center cereal certain chain chair chalk chamber champion change channel
chapter charge charm chase cheap check cheek cheese cherry chess chest chicken chief child
chimney choice choose chorus chrome church cinema circle circus citizen civil claim
clarify class classic clean clear clerk clever cliff climate climb clinic clock close
closet cloth cloud clover coach coast cobweb coconut coffee collar collect college colony
color column combine comedy comfort comic command comment common company compass complex
concert conduct confirm connect consist contact content contest context control convert
cookie copper coral corner correct cotton couch cough council count country county couple
courage course cousin cover coyote crack cradle craft crane crash crater crayon cream
create credit creek cricket crime crisp critic crowd crown cruise crumb crush crystal
cuckoo culture cupboard curious current curtain cushion custom cycle dagger daily dairy
damage dance danger daring debate debris decade decide declare decline decorate deeply
defeat defend define degree delay delight deliver demand dentist depart depend deposit
depth deputy derive desert design desire detail detect develop device devote diamond diary
diesel differ digital dinner dinosaur direct dirty discover disease display distant divide
doctor dolphin domain donkey double dough dozen draft dragon drama drawer dream dress drift
drink drive driver drizzle during dwarf dynamic eager eagle early earth easily eastern
economy edition editor effect effort eight either elbow elder elect elegant element
elephant elevator eleven elite email embark embrace emerge emotion empire employ empty
enable enact endless endorse enemy energy engage engine enhance enjoy enormous enough
enrich ensure enter entire entry envelope episode equal equator erase erode errand error
escape essay estate eternal ethics evening event evident evolve exact example excess
exchange excite exclude excuse execute exercise exhaust exhibit exile exist exotic expand
expect expert explain explode explore export expose express extend extra eyebrow fabric
factor factory faint fairy faith falcon family famous fancy fantasy farmer fashion father
faucet fault favor feather feature fellow fence ferry festival fever fiber fiction field
fierce fifteen fight figure final finger finish flame flavor fleet flight float flock
floor flower fluid flute focus folder follow forest forget formal format former fortune
forward fossil fountain fragile frame freedom freeze freight fresh friend fringe frost
frozen fruit fudge funnel furnace future gadget galaxy gallery gallon gamble garage garden
garlic garment gather gauge gazelle general genius gentle genuine gesture ghost giant
ginger giraffe glacier glance glass glide glimpse global gloomy glory glove goblin golden
gospel gossip govern grace grade grain grammar grand granite grape graph grass gravel
gravity great greedy green greet grief grill grocery ground group growth guard guess guest
guide guitar gutter habit hammer hamster handle happen harbor hardly harmony harvest hatch
haunt hazard header health heart heater heaven heavy hedge height helmet helpful herald
herbal hidden highway hiking history hobby hockey holiday hollow honest honey hoodie
horizon horror horse hospital hostile hotel humble humor hundred hunger hunter hurdle
hurry husband hybrid iceberg ideal identify ignore illegal illness image imagine impact
import impose improve impulse incense include income index indoor infant inform inherit
initial injury inland inner innocent input inquiry insect inside insist inspire install
instant intact intend invest invite island isolate issue ivory jacket jaguar jasmine
jealous jelly jersey jewel jigsaw jockey journey judge juggle juice jumble jungle junior
justice kayak kernel kettle keyboard kidney kingdom kitchen kitten knife knight knock
label labor ladder ladle lagoon lantern laptop large laser latch later laugh launch
laundry lawyer layer leader league learn leather lecture legend lemon length leopard
lesson letter lettuce level liberty library license light limit linen liquid listen
little lively lizard lobby lobster local locker lodge logic lonely lottery lounge loyal
lucky luggage lumber lunar lunch luxury lyrics machine magic magnet maiden mailbox major
mammal manage mango manner mantle manual maple marble margin marine market marriage marsh
mascot master match matter meadow measure medal medium melody melon member memory mental
mentor merchant mercy merit message metal method middle midnight mighty million mimic
mineral minor minute miracle mirror mischief missile mission mistake mixture mobile model
modern modest moment monitor monkey monster month morning mosaic mosquito mother motion
motor mountain mouse mouth muffin multiply muscle museum mushroom music mustard mutual
mystery napkin narrow nation native nature nearby nectar needle neglect neither nephew
nerve network neutral never newborn noble nobody noise normal north notable nothing notice
novel number nurse nutmeg oasis object oblige obscure observe obtain obvious occur ocean
offend office often olive omelet onion online opera opinion oppose option orange orbit
orchard order organ origin orphan ostrich outcome outdoor outer output outside overall
owner oxygen oyster package paddle palace panda panel panic panther paper parade parent
parrot partner party passage passion pasta pastel patch patience patrol pattern pause
peace peach peanut pearl pebble pelican penalty pencil people pepper perfect perform
permit person phone photo phrase physics piano picnic picture piece pigeon pillow pilot
pinch pioneer pirate pistol pitch pizza planet plastic plate player please pledge plenty
pocket poetry point polar police polish pollen popcorn popular portion position potato
pottery powder power prairie praise predict prefer prepare present pretty prevent price
pride primary prince print priority prison private prize problem process produce profit
program project promise proof proper protect proud provide public pudding pulse pumpkin
punch pupil puppet puppy purple purpose puzzle pyramid quality quarter queen query quest
quick quiet quilt quote rabbit raccoon radar radio railway rainbow raise rally random
range rapid rascal rather raven razor reach react reader ready realm reason rebel recall
receipt recipe record recover reduce reflect reform refuse region regret reject relax
relief remain remedy remind remote remove render rental repair repeat replace report
rescue resist resort result retire return reveal review reward rhythm ribbon rider ridge
rifle right rigid river roast robot rocket rodeo roller rookie rotate rough round route
royal rubber rumor runway rural rustic saddle safari safety sailor salad salmon salute
sample sandal satisfy saucer sausage scale scatter scene scheme school science scissors
scooter score scout scrap scream screen script sculpt season second secret section secure
select seminar senior sense series serve session settle seven shadow shallow shampoo shape
share shark sharp shelf shell shelter sheriff shield shift shine shiver shock shoulder
shovel shower shrimp shuffle signal silent silver simple siren sister skate sketch skill
slender slice slogan smart smile smoke snack snake sneeze soccer social socket soldier
solid solution sorrow sound source space spark speaker special speech spider spinach
spirit splash sponge spoon sport spray spring sprout square squash squirrel stable stadium
staff stage stairs stamp stand staple start station statue steady steam steel stereo
stick still stingy stitch stock stomach stone storm story stove strange straw stream
street strike string strong student studio stumble style subject submit subway sudden
sugar summer summit sunset supply supreme surface surgeon surprise survey suspect swallow
swamp sweater sweet swift swing switch sword symbol symptom syrup system table tablet
tackle tactic talent target teacher temple tenant tennis tension terrain theater theory
thing thirst thought thread threat thrive throat thumb thunder ticket tiger timber tissue
title toast tobacco today toddler toilet tomato tongue tonight topic tornado tortoise
total tourist towel tower track trade traffic tragic trail train transfer travel treasure
treaty trend trial tribe trick trigger trophy tropical trouble truck trumpet trust truth
tunnel turkey turtle twelve twenty twice twist typical umbrella unable uncle uncover under
unfair unfold uniform unique universe unknown unlock until unusual update upgrade uphold
upper upset urban usage useful usual utility vacant vacuum valley valve vanish vapor
various vault vehicle velvet vendor venture venue verbal verdict version vessel veteran
viable vibrant victory video village vintage violin virtual virus visible visit visual
vital vivid vocal volcano voyage wagon waiter walnut wander warfare warrior wealth weapon
weasel weather wedding weekend weird welcome western whale wheat wheel whisper whistle
widget width window winter wisdom witness wizard woman wonder wooden worker worry worth
wrangle wreck wrestle wrist writer yacht yellow yesterday yogurt young youth zebra zigzag
zipper
"""
WORD_POOL = sorted({w for w in WORD_POOL_TEXT.split() if 5 <= len(w) <= 10 and w.isalpha()})
WORD_COUNT = 20
WORD_SLOT_MS = 1000 // 3        # 3 words per second
WORD_SHOW_MS = 270              # visible part of each slot; the rest is a blank gap


def generate_word_sequence():
    """WORD_COUNT words with exactly one repeat, never shown back to back."""
    words = random.sample(WORD_POOL, WORD_COUNT - 1)
    dup_index = random.randrange(len(words))
    while True:
        pos = random.randrange(WORD_COUNT)
        seq = words[:pos] + [words[dup_index]] + words[pos:]
        first, second = [i for i, w in enumerate(seq) if w == words[dup_index]]
        if second - first >= 2:
            return seq, words[dup_index]


class WordMemoryPuzzle(Puzzle):
    """Watch 20 words flash past, then type the one that appeared twice."""
    title = "Words"

    def __init__(self):
        super().__init__()
        self.new_round()
        self.message = None

    def new_round(self):
        self.sequence, self.answer = generate_word_sequence()
        self.phase = "ready"              # ready -> showing -> typing
        self.started_at = None
        self.typed = ""

    def layout(self, rect):
        s = scale_of(rect)
        play = pygame.Rect(0, 0, 200 * s, 64 * s)
        play.center = (rect.centerx, rect.centery + 70 * s)
        box = pygame.Rect(0, 0, 420 * s, 64 * s)
        box.center = (rect.centerx, rect.centery + 10 * s)
        return play, box

    def on_mouse_down(self, pos, rect, button):
        play, _ = self.layout(rect)
        if button == 1 and self.phase == "ready" and not self.solved and play.collidepoint(pos):
            self.phase = "showing"
            self.started_at = pygame.time.get_ticks()
            self.message = None
            return True
        return False

    def update(self, now):
        if self.phase == "showing" and now - self.started_at >= WORD_COUNT * WORD_SLOT_MS:
            self.phase = "typing"

    def on_key(self, event):
        if self.phase != "typing" or self.solved:
            return
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if not self.typed:
                return
            if self.typed.lower() == self.answer:
                self.mark_solved()
            else:
                self.penalty_ms += PENALTY_MS
                self.message = f"Wrong - it was \"{self.answer}\". -5 s. New words."
                self.new_round()
        elif event.key == pygame.K_BACKSPACE:
            self.typed = self.typed[:-1]
        elif event.unicode.isalpha() and len(self.typed) < 12:
            self.typed += event.unicode.lower()

    def draw(self, surface, rect, fonts, mouse):
        draw_module_frame(surface, rect, fonts, "WORD MEMORY", self.solved)
        s = scale_of(rect)
        play, box = self.layout(rect)
        if self.solved:
            img = fonts["word"].render(self.answer, True, TIMER_DONE)
            surface.blit(img, img.get_rect(center=rect.center))
            draw_status(surface, rect, fonts, "SOLVED", TIMER_DONE)
        elif self.phase == "ready":
            for i, line in enumerate(("20 words will flash past, 3 per second.",
                                      "Exactly one appears twice. Type it afterwards.")):
                img = fonts["main"].render(line, True, TEXT)
                surface.blit(img, img.get_rect(center=(rect.centerx,
                                                       rect.centery + (-90 + i * 40) * s)))
            draw_button(surface, play, "Play", fonts["main"], play.collidepoint(mouse))
            if self.message:
                draw_status(surface, rect, fonts, self.message, TIMER_RUNNING)
        elif self.phase == "showing":
            elapsed = pygame.time.get_ticks() - self.started_at
            i = min(WORD_COUNT - 1, elapsed // WORD_SLOT_MS)
            if elapsed % WORD_SLOT_MS < WORD_SHOW_MS:
                img = fonts["word"].render(self.sequence[i], True, TEXT)
                surface.blit(img, img.get_rect(center=rect.center))
            bar = pygame.Rect(rect.x + 60 * s, rect.bottom - 50 * s, rect.w - 120 * s, max(2, 8 * s))
            pygame.draw.rect(surface, PANEL, bar, border_radius=bar.h // 2)
            pygame.draw.rect(surface, DIM, (bar.x, bar.y, bar.w * (i + 1) / WORD_COUNT, bar.h),
                             border_radius=bar.h // 2)
        else:
            img = fonts["main"].render("Which word appeared twice?", True, TEXT)
            surface.blit(img, img.get_rect(center=(rect.centerx, rect.centery - 60 * s)))
            pygame.draw.rect(surface, TIMER_TILE, box, border_radius=max(2, int(10 * s)))
            pygame.draw.rect(surface, DIM, box, max(1, int(2 * s)), border_radius=max(2, int(10 * s)))
            caret = "_" if (pygame.time.get_ticks() // 400) % 2 == 0 else " "
            img = fonts["main"].render(self.typed + caret, True, TEXT)
            surface.blit(img, img.get_rect(midleft=(box.x + 16 * s, box.centery)))
            draw_status(surface, rect, fonts, "Type the word, then press Enter", DIM)

    @staticmethod
    def manual_general():
        return [("text", "Press Play and watch 20 words flash past. Exactly one "
                         "word appears twice; type it and press Enter. A wrong answer costs "
                         "5 seconds and deals a new set of words.")]


# ---- 4. Blue light -------------------------------------------------------------
BLUE_FLASHES = 3                # flashes per cycle
BLUE_ON_MS = 1000
BLUE_GAP_MS = (5000, 20000)
BLUE_CYCLE_PENALTY_MS = 10_000  # lost when a whole cycle passes without a catch
LAMP_OFF = (30, 32, 40)
LAMP_BLUE = (60, 140, 255)


class BlueLightPuzzle(Puzzle):
    """Runs from the start of the round: one click while the light is blue solves it.

    The light flashes in cycles of BLUE_FLASHES. Each cycle's timing is fixed when
    it starts. If a whole cycle passes uncaught, BLUE_CYCLE_PENALTY_MS is lost and
    a fresh cycle begins, until the timer runs out. Clicking while it is not
    blue costs PENALTY_MS.
    """
    title = "Blue light"

    def __init__(self):
        super().__init__()
        self.new_cycle(pygame.time.get_ticks())

    def new_cycle(self, t):
        # A 5-20 s gap before each 1 s flash.
        self.flashes = []
        for _ in range(BLUE_FLASHES):
            t += random.randint(*BLUE_GAP_MS)
            self.flashes.append((t, t + BLUE_ON_MS))
            t += BLUE_ON_MS

    def current(self, now):
        for i, (on, off) in enumerate(self.flashes):
            if on <= now < off:
                return i
        return None

    def update(self, now):
        if not self.solved and now >= self.flashes[-1][1]:
            self.penalty_ms += BLUE_CYCLE_PENALTY_MS
            self.new_cycle(self.flashes[-1][1])

    def press(self):
        if self.solved:
            return
        if self.current(pygame.time.get_ticks()) is not None:
            self.mark_solved()
        else:
            self.penalty_ms += PENALTY_MS

    def on_mouse_down(self, pos, rect, button):
        if button != 1 or not rect.collidepoint(pos):
            return False
        self.press()
        return True

    def draw_lamp(self, surface, center, radius):
        i = None if self.solved else self.current(pygame.time.get_ticks())
        if i is not None:
            pygame.draw.circle(surface, (40, 80, 160), center, radius * 1.25)
            color = LAMP_BLUE
        elif self.solved:
            color = TILE_ON
        else:
            color = LAMP_OFF
        pygame.draw.circle(surface, color, center, radius)
        pygame.draw.circle(surface, SOCKET_RIM, center, radius, 2)

    def draw(self, surface, rect, fonts, mouse):
        draw_module_frame(surface, rect, fonts, "BLUE LIGHT", self.solved)
        self.draw_lamp(surface, rect.center, rect.w * 0.26)
        if self.solved:
            draw_status(surface, rect, fonts, "SOLVED", TIMER_DONE)

    @staticmethod
    def manual_general():
        return [("text", "Every so often it turns blue for 1 second. Click it once "
                         "while it is blue to solve it. Clicking it while it is not blue costs "
                         "5 seconds. Every 3 blue flashes that pass without a click cost 10 "
                         "seconds. If the light is off screen or this book is open, a copy "
                         "shows in the top-right corner and can be clicked there.")]


# ---- 5. Lights -----------------------------------------------------------------
LIGHTS_N = 5
LIGHT_ON = (250, 205, 80)
LIGHT_OFF = (45, 48, 58)


class LightsPuzzle(Puzzle):
    """5x5 lights; clicking one flips it and its four side neighbours. Turn all off."""
    title = "Lights"

    def __init__(self):
        super().__init__()
        # Scramble an all-off board with real presses, so it is always solvable.
        cells = [(r, c) for r in range(LIGHTS_N) for c in range(LIGHTS_N)]
        while True:
            self.grid = [[False] * LIGHTS_N for _ in range(LIGHTS_N)]
            for r, c in random.sample(cells, random.randint(6, 12)):
                self.flip(r, c)
            if any(any(row) for row in self.grid):
                break

    def flip(self, r, c):
        for dr, dc in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
            rr, cc = r + dr, c + dc
            if 0 <= rr < LIGHTS_N and 0 <= cc < LIGHTS_N:
                self.grid[rr][cc] = not self.grid[rr][cc]

    def cell_rect(self, rect, r, c):
        side = min(rect.w, rect.h) * 0.66
        cell = side / LIGHTS_N
        x0 = rect.centerx - side / 2
        y0 = rect.centery - side / 2
        pad = cell * 0.07
        return pygame.Rect(x0 + c * cell + pad, y0 + r * cell + pad, cell - 2 * pad, cell - 2 * pad)

    def on_mouse_down(self, pos, rect, button):
        if button != 1:
            return False
        for r in range(LIGHTS_N):
            for c in range(LIGHTS_N):
                if self.cell_rect(rect, r, c).collidepoint(pos):
                    if not self.solved:
                        self.flip(r, c)
                        if not any(any(row) for row in self.grid):
                            self.mark_solved()
                    return True
        return False

    def draw(self, surface, rect, fonts, mouse):
        draw_module_frame(surface, rect, fonts, "LIGHTS", self.solved)
        for r in range(LIGHTS_N):
            for c in range(LIGHTS_N):
                cr = self.cell_rect(rect, r, c)
                radius = max(2, int(cr.w * 0.14))
                pygame.draw.rect(surface, LIGHT_ON if self.grid[r][c] else LIGHT_OFF, cr,
                                 border_radius=radius)
                if not self.solved and cr.collidepoint(mouse):
                    pygame.draw.rect(surface, TEXT, cr, max(1, int(cr.w * 0.04)), border_radius=radius)
        if self.solved:
            draw_status(surface, rect, fonts, "SOLVED", TIMER_DONE)
        else:
            draw_status(surface, rect, fonts, "Turn every light off", DIM)

    @staticmethod
    def manual_general():
        return [("text", "Clicking a square flips it and the (up to) four squares touching its "
                         "sides, on to off and off to on. Turn every light off.")]


# ---- 6. Trades -----------------------------------------------------------------
SHAPES = ("circle", "triangle", "square")
SHAPE_COLORS = {"circle": (240, 150, 50), "triangle": (90, 200, 120), "square": (70, 140, 230)}
INV_COLS, INV_ROWS = 6, 3
MAX_STACK = 16
TRADE_SLOT = (28, 30, 38)
TRADE_SLOT_RIM = (95, 100, 118)


def draw_shape(surface, kind, center, size):
    x, y = center
    h = size / 2
    color = SHAPE_COLORS[kind]
    if kind == "circle":
        pygame.draw.circle(surface, color, center, h)
    elif kind == "triangle":
        pygame.draw.polygon(surface, color, [(x, y - h), (x + h, y + h * 0.8), (x - h, y + h * 0.8)])
    else:
        pygame.draw.rect(surface, color, (x - h * 0.85, y - h * 0.85, h * 1.7, h * 1.7),
                         border_radius=max(1, int(size * 0.08)))


def apply_trade(state, rules, src):
    dst, a, b = rules[src]
    state = dict(state)
    state[src] -= a
    state[dst] += b
    return state


def min_trades(start, target, rules, cap=60, max_depth=20):
    """Fewest trades from start to target (BFS), or None if unreachable within the caps."""
    key = lambda st: tuple(st[k] for k in SHAPES)
    goal = key(target)
    frontier, seen = [start], {key(start)}
    for depth in range(max_depth + 1):
        nxt = []
        for st in frontier:
            if key(st) == goal:
                return depth
            for src, (dst, a, b) in rules.items():
                if st[src] >= a and st[dst] + b <= cap:
                    new = apply_trade(st, rules, src)
                    if key(new) not in seen:
                        seen.add(key(new))
                        nxt.append(new)
        frontier = nxt
    return None


def has_gain_cycle(rules):
    """True if some loop of trades returns to its start shape with at least as many."""
    for first in rules:
        ratio, shape = 1.0, first
        for _ in range(len(SHAPES)):
            if shape not in rules:
                break
            dst, a, b = rules[shape]
            ratio *= b / a
            shape = dst
            if shape == first:
                if ratio >= 1:
                    return True
                break
    return False


def generate_trades():
    """Start counts, one-way rates (at most one per source shape), and a target that is
    reached from the start by a random series of legal trades (so it is solvable)."""
    while True:
        start = {k: random.randint(2, 12) for k in SHAPES}
        rules = {}
        for src in SHAPES:
            if random.random() < 0.85:
                a, b = random.sample(range(1, 5), 2)
                rules[src] = (random.choice([k for k in SHAPES if k != src]), a, b)
        if len(rules) < 2 or has_gain_cycle(rules):
            continue
        state, made = dict(start), 0
        wanted = random.randint(3, 7)
        while made < wanted:
            usable = [src for src, (_, a, _) in rules.items() if state[src] >= a]
            if not usable:
                break
            state = apply_trade(state, rules, random.choice(usable))
            made += 1
        if made < 3 or max(state.values()) > 40:
            continue
        depth = min_trades(start, state, rules)
        if depth is not None and depth >= 3:
            return start, state, rules


class TradePuzzle(Puzzle):
    """Minecraft-style inventory: trade shapes through one-way rates to hit a goal."""
    title = "Trades"

    def __init__(self):
        super().__init__()
        self.start, self.target, self.rules = generate_trades()
        self.restock()

    def restock(self):
        self.inv = [None] * (INV_COLS * INV_ROWS)     # each slot: None or (shape, count)
        self.input = None
        self.cursor = None                            # stack held on the mouse
        self.press_slot = None                        # slot a drag started from
        free = random.sample(range(len(self.inv)), len(self.inv))
        for kind in SHAPES:
            n = self.start[kind]
            while n > 0:
                take = min(n, MAX_STACK)
                self.inv[free.pop()] = (kind, take)
                n -= take

    # ---- geometry ----
    def slot_rects(self, rect):
        s = scale_of(rect)
        size, step = 64 * s, 72 * s
        rects = {}
        x0 = rect.centerx - (INV_COLS * 72 - 8) / 2 * s
        y0 = rect.y + 300 * s
        for i in range(INV_COLS * INV_ROWS):
            r, c = divmod(i, INV_COLS)
            rects[("inv", i)] = pygame.Rect(x0 + c * step, y0 + r * step, size, size)
        for sid, dx in ((("in",), -110), (("out",), 110)):
            box = pygame.Rect(0, 0, size * 1.15, size * 1.15)
            box.center = (rect.centerx + dx * s, rect.y + 205 * s)
            rects[sid] = box
        return rects

    def slot_at(self, rect, pos):
        for sid, r in self.slot_rects(rect).items():
            if r.collidepoint(pos):
                return sid
        return None

    # ---- stack bookkeeping ----
    def get(self, sid):
        return self.input if sid[0] == "in" else self.inv[sid[1]]

    def put(self, sid, stack):
        if stack is not None and stack[1] <= 0:
            stack = None
        if sid[0] == "in":
            self.input = stack
        else:
            self.inv[sid[1]] = stack

    def owned(self):
        counts = dict.fromkeys(SHAPES, 0)
        for stack in self.inv + [self.input, self.cursor]:
            if stack:
                counts[stack[0]] += stack[1]
        return counts

    def room_for(self, kind):
        return sum(MAX_STACK - st[1] if st and st[0] == kind else (MAX_STACK if st is None else 0)
                   for st in self.inv)

    def add_to_inventory(self, kind, n):
        """Merge into matching stacks, then empty slots. Returns what didn't fit."""
        for pass_empty in (False, True):
            for i, st in enumerate(self.inv):
                if n == 0:
                    return 0
                if pass_empty and st is None:
                    take = min(n, MAX_STACK)
                    self.inv[i] = (kind, take)
                    n -= take
                elif not pass_empty and st and st[0] == kind and st[1] < MAX_STACK:
                    take = min(n, MAX_STACK - st[1])
                    self.inv[i] = (kind, st[1] + take)
                    n -= take
        return n

    def offer(self):
        """(shape, count) the output box currently shows, if the input pays for a trade."""
        if self.input and self.input[0] in self.rules:
            dst, a, b = self.rules[self.input[0]]
            if self.input[1] >= a:
                return dst, b
        return None

    def trade_once(self):
        _, a, _ = self.rules[self.input[0]]
        self.put(("in",), (self.input[0], self.input[1] - a))

    # ---- clicks (Minecraft rules) ----
    def click_slot(self, sid, button, shift):
        if sid == ("out",):
            self.click_output(shift)
            return
        stack, held = self.get(sid), self.cursor
        if shift and button == 1:
            if stack is None:
                return
            if sid == ("in",):                             # input -> inventory
                self.put(sid, (stack[0], self.add_to_inventory(*stack)))
            elif self.input is None:                       # inventory -> empty input
                self.input, self.inv[sid[1]] = stack, None
            elif self.input[0] == stack[0]:                # inventory -> matching input
                moved = min(MAX_STACK - self.input[1], stack[1])
                self.input = (stack[0], self.input[1] + moved)
                self.put(sid, (stack[0], stack[1] - moved))
            return
        if button == 1:
            if held is None:                               # pick up the whole stack
                self.cursor = stack
                self.put(sid, None)
            elif stack is None:                            # place the whole stack
                self.put(sid, held)
                self.cursor = None
            elif stack[0] == held[0]:                      # merge as much as fits
                moved = min(MAX_STACK - stack[1], held[1])
                self.put(sid, (stack[0], stack[1] + moved))
                self.cursor = (held[0], held[1] - moved) if held[1] > moved else None
            else:                                          # different shape: swap
                self.put(sid, held)
                self.cursor = stack
        elif button == 3:
            if held is None:
                if stack:                                  # pick up half (rounded up)
                    half = (stack[1] + 1) // 2
                    self.cursor = (stack[0], half)
                    self.put(sid, (stack[0], stack[1] - half))
            elif stack is None or (stack[0] == held[0] and stack[1] < MAX_STACK):
                self.put(sid, (held[0], (stack[1] if stack else 0) + 1))   # drop one
                self.cursor = (held[0], held[1] - 1) if held[1] > 1 else None
            elif stack[0] != held[0]:
                self.put(sid, held)
                self.cursor = stack

    def click_output(self, shift):
        offer = self.offer()
        if offer is None:
            return
        kind, n = offer
        if shift:                                          # as many trades as possible
            while offer and self.room_for(kind) >= n:
                self.trade_once()
                self.add_to_inventory(kind, n)
                offer = self.offer()
        elif self.cursor is None or (self.cursor[0] == kind and self.cursor[1] + n <= MAX_STACK):
            self.trade_once()
            self.cursor = (kind, (self.cursor[1] if self.cursor else 0) + n)

    def check(self):
        if self.cursor is None and self.input is None and self.owned() == self.target:
            self.mark_solved()

    # ---- input ----
    def on_mouse_down(self, pos, rect, button):
        if self.solved or button not in (1, 3):
            return False
        if button == 1 and reset_button_rect(rect).collidepoint(pos):
            self.restock()
            return True
        sid = self.slot_at(rect, pos)
        if sid is None:
            return False
        shift = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
        was_holding = self.cursor is not None
        self.click_slot(sid, button, shift)
        # A press that picked something up can be finished as a drag-and-drop.
        self.press_slot = sid if (button == 1 and not shift and not was_holding
                                  and self.cursor is not None) else None
        self.check()
        return True

    def on_mouse_up(self, pos, rect):
        if self.press_slot is not None and self.cursor is not None:
            sid = self.slot_at(rect, pos)
            if sid is not None and sid not in (self.press_slot, ("out",)):
                self.click_slot(sid, 1, False)
                self.check()
        self.press_slot = None

    # ---- drawing ----
    def draw_stack(self, surface, stack, center, size, fonts):
        draw_shape(surface, stack[0], center, size * 0.55)
        if stack[1] > 1:
            img = fonts["main"].render(str(stack[1]), True, TEXT)
            surface.blit(img, img.get_rect(bottomright=(center[0] + size * 0.5, center[1] + size * 0.55)))

    def draw(self, surface, rect, fonts, mouse):
        draw_module_frame(surface, rect, fonts, "TRADES", self.solved)
        s = scale_of(rect)
        if not self.solved:
            reset = reset_button_rect(rect)
            draw_button(surface, reset, "Reset", fonts["main"], reset.collidepoint(mouse))

        # Goal row: owned / goal for each shape.
        owned = self.owned()
        label = fonts["main"].render("Goal", True, DIM)
        total_w = label.get_width() + 3 * 150 * s
        x = rect.centerx - total_w / 2
        y = rect.y + 100 * s
        surface.blit(label, label.get_rect(midleft=(x, y)))
        x += label.get_width() + 30 * s
        for kind in SHAPES:
            draw_shape(surface, kind, (x + 14 * s, y), 30 * s)
            done = owned[kind] == self.target[kind]
            img = fonts["main"].render(f"{owned[kind]} / {self.target[kind]}", True,
                                       TIMER_DONE if done else TEXT)
            surface.blit(img, img.get_rect(midleft=(x + 38 * s, y)))
            x += 150 * s

        rects = self.slot_rects(rect)
        # Trade row: input -> output.
        a, b = rects[("in",)], rects[("out",)]
        ay = a.centery
        pygame.draw.line(surface, DIM, (a.right + 20 * s, ay), (b.left - 24 * s, ay), max(1, int(4 * s)))
        pygame.draw.polygon(surface, DIM, [(b.left - 12 * s, ay), (b.left - 30 * s, ay - 12 * s),
                                           (b.left - 30 * s, ay + 12 * s)])
        for sid, rr in rects.items():
            hover = not self.solved and rr.collidepoint(mouse)
            pygame.draw.rect(surface, TRADE_SLOT, rr, border_radius=max(2, int(8 * s)))
            pygame.draw.rect(surface, TEXT if hover else TRADE_SLOT_RIM, rr, max(1, int(2 * s)),
                             border_radius=max(2, int(8 * s)))
            stack = self.offer() if sid == ("out",) else self.get(sid)
            if stack:
                self.draw_stack(surface, stack, rr.center, rr.w, fonts)
        for sid, text in ((("in",), "In"), (("out",), "Out")):
            img = fonts["small"].render(text, True, DIM)
            surface.blit(img, img.get_rect(midbottom=(rects[sid].centerx, rects[sid].top - 6 * s)))

        if self.solved:
            draw_status(surface, rect, fonts, "SOLVED", TIMER_DONE)
        elif owned == self.target:
            draw_status(surface, rect, fonts, "Put everything back in the inventory", DIM)
        else:
            draw_status(surface, rect, fonts, "Trade until your shapes match the goal", DIM)

        if self.cursor and rect.collidepoint(mouse):
            self.draw_stack(surface, self.cursor, mouse, 64 * s, fonts)

    def manual(self, position):
        def amount(kind, n):
            return f"{n} {kind}{'' if n == 1 else 's'}"
        return [("rule", f"{amount(src, a)}  ->  {amount(dst, b)}")
                for src, (dst, a, b) in sorted(self.rules.items())]

    @staticmethod
    def manual_general():
        return [("text", "Trade shapes until you own exactly the goal amounts, with everything "
                         "back in the inventory. Put shapes in the In box; if they pay for a "
                         "trade below, the Out box shows what you get. Trades only go one way. "
                         "Left-click picks up or places a stack (or drag it). Right-click picks "
                         "up half a stack, or places one shape. Shift-click moves a stack "
                         "between inventory and In. Click Out to take one trade; shift-click "
                         "Out to take as many as fit. Reset restores the starting shapes.")]


# ---- 7. Instructions -----------------------------------------------------------
INSTR_N = 3
INSTR_COUNT = 10                # including the START line
INSTR_STARTS = {"TOP LEFT": (0, 0), "TOP RIGHT": (0, INSTR_N - 1),
                "BOTTOM LEFT": (INSTR_N - 1, 0), "BOTTOM RIGHT": (INSTR_N - 1, INSTR_N - 1),
                "CENTER": (INSTR_N // 2, INSTR_N // 2)}
INSTR_MOVES = {"UP": (-1, 0), "DOWN": (1, 0), "LEFT": (0, -1), "RIGHT": (0, 1)}
INSTR_TOGGLES = {"ABOVE": (-1, 0), "BELOW": (1, 0), "LEFT": (0, -1), "RIGHT": (0, 1)}
INSTR_ON = (235, 90, 80)
INSTR_OFF = (45, 48, 58)


def generate_instructions():
    """START line plus moves/toggles that never leave the grid. Returns the
    instruction text and the set of cells left on after following them all."""
    def inside(r, c):
        return 0 <= r < INSTR_N and 0 <= c < INSTR_N

    while True:
        name = random.choice(list(INSTR_STARTS))
        r, c = INSTR_STARTS[name]
        lines, on, moves = [f"START at {name}"], set(), 0
        while len(lines) < INSTR_COUNT:
            kind = random.choices(("move", "here", "near"), weights=(45, 25, 30))[0]
            if kind == "here":
                on ^= {(r, c)}
                lines.append("TOGGLE CURRENT")
                continue
            table = INSTR_MOVES if kind == "move" else INSTR_TOGGLES
            word, (dr, dc) = random.choice([(w, d) for w, d in table.items()
                                            if inside(r + d[0], c + d[1])])
            if kind == "move":
                r, c = r + dr, c + dc
                moves += 1
                lines.append(f"MOVE {word}")
            else:
                on ^= {(r + dr, c + dc)}
                lines.append(f"TOGGLE {word}")
        if len(on) >= 3 and moves >= 3:
            return lines, on


class InstructionPuzzle(Puzzle):
    """3x3 toggle grid; the rule book lists steps whose end result is the answer."""
    title = "Instructions"

    def __init__(self):
        super().__init__()
        self.lines, self.answer = generate_instructions()
        self.on = set()

    def cell_rect(self, rect, r, c):
        side = min(rect.w, rect.h) * 0.72
        cell = side / INSTR_N
        x0 = rect.centerx - side / 2
        y0 = rect.centery - side / 2 + 6 * scale_of(rect)
        pad = max(1, cell * 0.06)
        return pygame.Rect(x0 + c * cell + pad, y0 + r * cell + pad, cell - 2 * pad, cell - 2 * pad)

    def on_mouse_down(self, pos, rect, button):
        if button != 1:
            return False
        if reset_button_rect(rect).collidepoint(pos):
            if not self.solved:
                self.on = set()
            return True
        for r in range(INSTR_N):
            for c in range(INSTR_N):
                if self.cell_rect(rect, r, c).collidepoint(pos):
                    if not self.solved:
                        self.on ^= {(r, c)}
                        if self.on == self.answer:
                            self.mark_solved()
                    return True
        return False

    def draw(self, surface, rect, fonts, mouse):
        draw_module_frame(surface, rect, fonts, "INSTRUCTIONS", self.solved)
        if not self.solved:
            reset = reset_button_rect(rect)
            draw_button(surface, reset, "Reset", fonts["main"], reset.collidepoint(mouse))
        for r in range(INSTR_N):
            for c in range(INSTR_N):
                cr = self.cell_rect(rect, r, c)
                radius = max(1, int(cr.w * 0.15))
                pygame.draw.rect(surface, INSTR_ON if (r, c) in self.on else INSTR_OFF, cr,
                                 border_radius=radius)
                if not self.solved and cr.collidepoint(mouse):
                    pygame.draw.rect(surface, TEXT, cr, max(1, int(cr.w * 0.06)), border_radius=radius)
        if self.solved:
            draw_status(surface, rect, fonts, "SOLVED", TIMER_DONE)
        else:
            draw_status(surface, rect, fonts, "Click tiles to match the instructions", DIM)

    def manual(self, position):
        return [("rule", line) for line in self.lines]

    @staticmethod
    def manual_general():
        return [("text", "All tiles start off; click a tile to toggle it. Follow the steps "
                         "below from the START tile: MOVE shifts your position one tile, "
                         "TOGGLE CURRENT flips the tile you are on, and TOGGLE ABOVE / BELOW / "
                         "LEFT / RIGHT flips the neighbouring tile without moving. Only the "
                         "final pattern is checked.")]


# ---- 8. Balance (metronome) ----------------------------------------------------
MET_MAX_ANGLE = 1.25            # rad from upright where the arm rests on its side
MET_GRAVITY = 1.6               # angular accel = MET_GRAVITY * sin(angle): tips harder when lower
MET_DAMPING = 0.3               # per second
MET_IMPULSE = 0.9               # rad/s added per button press
MET_ZONE_HALF = 0.26            # half-width of the green zone, rad
MET_HOLD_S = 3.0                # consecutive seconds in the zone to solve
MET_GRACE_S = 0.2               # time outside the zone that doesn't break the streak
MET_STEP_S = 1 / 240            # physics substep
MET_BUTTON_RANGE = (0.2, 0.85)  # button heights, as a fraction of the module height
MET_MIN_JUMP = 0.3              # a pressed button moves at least this far
MET_ARM = (150, 155, 170)
MET_ZONE = (60, 150, 90)


class MetronomePuzzle(Puzzle):
    """Inverted-pendulum arm kept inside a drifting green zone with two impulse buttons."""
    title = "Balance"

    def __init__(self):
        super().__init__()
        self.angle = random.choice((-1, 1)) * MET_MAX_ANGLE     # 0 = upright, + = right
        self.speed = 0.0
        self.streak = 0.0                                       # seconds in the zone
        self.outside = 0.0                                      # seconds out since last in
        self.t = 0.0
        self.phase = (random.uniform(0, 6.3), random.uniform(0, 6.3))
        self.button_y = {"left": random.uniform(*MET_BUTTON_RANGE),
                         "right": random.uniform(*MET_BUTTON_RANGE)}
        self.last = pygame.time.get_ticks()

    @staticmethod
    def jump(y):
        """New button height at least MET_MIN_JUMP away from y."""
        lo, hi = MET_BUTTON_RANGE
        choices = [(lo, y - MET_MIN_JUMP), (y + MET_MIN_JUMP, hi)]
        spans = [(a, b) for a, b in choices if b > a]
        a, b = random.choices(spans, weights=[b - a for a, b in spans])[0]
        return random.uniform(a, b)

    def zone_center(self):
        """Smooth drift (two incommensurate sines) kept inside the arm's range."""
        c = 0.55 * math.sin(0.45 * self.t + self.phase[0]) \
            + 0.25 * math.sin(1.05 * self.t + self.phase[1])
        limit = MET_MAX_ANGLE - MET_ZONE_HALF - 0.05
        return max(-limit, min(limit, c))

    def in_zone(self):
        return abs(self.angle - self.zone_center()) <= MET_ZONE_HALF

    def update(self, now):
        dt = min(0.05, (now - self.last) / 1000)    # cap so a hitch can't fling the arm
        self.last = now
        if self.solved:
            return
        while dt > 1e-9:
            h = min(MET_STEP_S, dt)
            dt -= h
            self.t += h
            self.speed += (MET_GRAVITY * math.sin(self.angle) - MET_DAMPING * self.speed) * h
            self.angle += self.speed * h
            if abs(self.angle) >= MET_MAX_ANGLE:     # resting against a side stop
                self.angle = math.copysign(MET_MAX_ANGLE, self.angle)
                self.speed = 0.0
            if self.in_zone():
                self.streak += h
                self.outside = 0.0
            else:
                self.outside += h
                if self.outside > MET_GRACE_S:
                    self.streak = 0.0
            if self.streak >= MET_HOLD_S:
                self.mark_solved()
                return

    def button_rect(self, rect, side):
        s = scale_of(rect)
        r = pygame.Rect(0, 0, 84 * s, 84 * s)
        x = rect.x + 60 * s if side == "left" else rect.right - 60 * s
        r.center = (x, rect.y + rect.h * self.button_y[side])
        return r

    def on_mouse_down(self, pos, rect, button):
        if button != 1:
            return False
        for side, push in (("left", -1), ("right", 1)):
            if self.button_rect(rect, side).collidepoint(pos):
                if not self.solved:
                    self.speed += push * MET_IMPULSE
                    self.button_y[side] = self.jump(self.button_y[side])
                return True
        return False

    def draw(self, surface, rect, fonts, mouse):
        draw_module_frame(surface, rect, fonts, "BALANCE", self.solved)
        s = scale_of(rect)
        pivot = (rect.centerx, rect.bottom - 110 * s)
        length = rect.h * 0.56

        def tip(a, r=length):
            return pivot[0] + r * math.sin(a), pivot[1] - r * math.cos(a)

        # Green zone as a wedge, plus faint marks for the side stops.
        c = self.zone_center()
        arc = [tip(c - MET_ZONE_HALF + i * MET_ZONE_HALF / 8) for i in range(17)]
        pygame.draw.polygon(surface, MET_ZONE, [pivot] + arc)
        for a in (-MET_MAX_ANGLE, MET_MAX_ANGLE):
            pygame.draw.line(surface, PANEL, pivot, tip(a), max(1, int(3 * s)))

        # Arm turns from grey to bright green as the streak builds.
        k = 1.0 if self.solved else min(1.0, self.streak / MET_HOLD_S)
        color = tuple(int(a + (b - a) * k) for a, b in zip(MET_ARM, TIMER_DONE))
        pygame.draw.line(surface, color, pivot, tip(self.angle), max(2, int(12 * s)))
        pygame.draw.circle(surface, color, tip(self.angle, length * 0.78), 26 * s)
        base = pygame.Rect(0, 0, 120 * s, 34 * s)
        base.midtop = (pivot[0], pivot[1] - 6 * s)
        pygame.draw.rect(surface, TIMER_TILE, base, border_radius=max(2, int(8 * s)))
        pygame.draw.circle(surface, color, pivot, 12 * s)

        for side in ("left", "right"):
            br = self.button_rect(rect, side)
            hover = not self.solved and br.collidepoint(mouse)
            pygame.draw.rect(surface, BUTTON_HOVER if hover else BUTTON, br,
                             border_radius=max(2, int(14 * s)))
            d = -1 if side == "left" else 1
            cx, cy, h = br.centerx, br.centery, br.h * 0.24
            pygame.draw.polygon(surface, TEXT, [(cx + d * h, cy), (cx - d * h * 0.7, cy - h),
                                                (cx - d * h * 0.7, cy + h)])

        if self.solved:
            draw_status(surface, rect, fonts, "SOLVED", TIMER_DONE)
        else:
            draw_status(surface, rect, fonts, "Hold the arm in the green for 3 seconds", DIM)

    @staticmethod
    def manual_general():
        return [("text", "The arm falls harder the further it leans. The left and right buttons "
                         "each push it that way, then jump to a new height. Keep the arm in the "
                         "moving green zone for 3 seconds in a row; slipping out for under 0.2 s "
                         "is forgiven. The arm turns greener as you get closer.")]


PUZZLE_POOL = [WirePuzzle, TangoPuzzle, WordMemoryPuzzle, BlueLightPuzzle,
               LightsPuzzle, TradePuzzle, InstructionPuzzle, MetronomePuzzle]
# Real puzzle types; each appears at most once per board, switches fill the rest.


# --- Game -----------------------------------------------------------------------
# Font roles: (family, size at MODULE_DESIGN scale, bold). Modules get these
# resized to their on-screen scale every frame (sizes are cached).
FONT_SPECS = {
    "main": ("segoeui,arial", 30, False),
    "small": ("segoeui,arial", 22, False),
    "big": ("segoeui,arial", 90, False),
    "word": ("consolas,couriernew,monospace", 64, True),
    "timer": ("consolas,couriernew,monospace", 106, True),
}


def ease_out_cubic(t):
    return 1 - (1 - t) ** 3


class Game:
    def __init__(self, screen):
        self.screen = screen
        self.W, self.H = screen.get_size()

        # World layout: the bomb as it appears at zoom 1. The camera maps it to the screen.
        side = int(min(self.W, self.H) * GRID_FRAC)
        self.tile_size = (side - 2 * TILE_GAP) // 3
        side = self.tile_size * 3 + 2 * TILE_GAP
        left = (self.W - side) // 2
        top = (self.H - side) // 2
        self.grid_rect = pygame.Rect(left, top, side, side)
        self.tiles = [
            pygame.Rect(left + c * (self.tile_size + TILE_GAP),
                        top + r * (self.tile_size + TILE_GAP),
                        self.tile_size, self.tile_size)
            for r in range(3) for c in range(3)
        ]
        self.min_zoom = 1.0
        self.max_zoom = MAX_TILE_FRAC * min(self.W, self.H) / self.tile_size

        self.font_cache = {}
        self.font = pygame.font.SysFont("segoeui,arial", 30)
        self.small_font = pygame.font.SysFont("segoeui,arial", 22)
        self.hud_timer_font = pygame.font.SysFont("consolas,couriernew,monospace", 34, bold=True)
        self.title_font = pygame.font.SysFont("georgia,timesnewroman,serif", 36, bold=True)
        self.book_fonts = {size: (pygame.font.SysFont("georgia,timesnewroman,serif", size),
                                  pygame.font.SysFont("georgia,timesnewroman,serif", size + 3, bold=True))
                           for size in BOOK_FONT_SIZES}
        self.big_font = pygame.font.SysFont("segoeui,arial", 84, bold=True)

        self.redo_rect = pygame.Rect(0, 0, 240, 70)
        self.redo_rect.center = (self.W // 2, self.H // 2 + 90)
        self.hud_timer_rect = pygame.Rect(24, 16, 260, 60)   # corner, clear of the focused module
        self.light_rect = pygame.Rect(self.W - 150, 16, 120, 120)
        self.reset()

    # ---- fonts ----
    def fonts_at(self, scale):
        fonts = {}
        for role, (family, base, bold) in FONT_SPECS.items():
            size = max(6, round(base * scale))
            key = (role, size)
            if key not in self.font_cache:
                self.font_cache[key] = pygame.font.SysFont(family, size, bold=bold)
            fonts[role] = self.font_cache[key]
        return fonts

    # ---- state ----
    def reset(self):
        self.start_ms = pygame.time.get_ticks()
        self.last_ms = self.start_ms
        slots = [i for i in range(9) if i != CENTER]
        random.shuffle(slots)
        kinds = random.sample(PUZZLE_POOL, min(len(PUZZLE_POOL), len(slots)))
        kinds += [SwitchPuzzle] * (len(slots) - len(kinds))
        self.puzzles = [None] * 9
        for slot, kind in zip(slots, kinds):
            self.puzzles[slot] = kind()
        self.blue = next((p for p in self.puzzles if isinstance(p, BlueLightPuzzle)), None)

        self.state = "running"             # running -> defused -> won | lost
        self.penalty_ms = 0
        self.penalty_at = None             # when the last penalty landed, for the "-N s" flash
        self.last_penalty = 0
        self.frozen_remaining = None       # remaining time captured when the timer stops
        self.defused_at = None
        self.book_open = False             # target state; book_anim eases toward it
        self.book_anim = 0.0               # 0 = hidden, 1 = fully up

        self.zoom = 1.0
        self.cam = [float(self.grid_rect.centerx), float(self.grid_rect.centery)]
        self.capture = None                # module that owns the current left-drag
        self.pan_button = None             # mouse button currently panning

    def remaining_ms(self):
        if self.frozen_remaining is not None:
            return self.frozen_remaining
        elapsed = pygame.time.get_ticks() - self.start_ms
        return max(0, TIME_LIMIT_MS - elapsed - self.penalty_ms)

    def all_solved(self):
        return all(p.solved for p in self.puzzles if p is not None)

    # ---- camera ----
    def to_screen_rect(self, r):
        z = self.zoom
        x0 = (r.left - self.cam[0]) * z + self.W / 2
        y0 = (r.top - self.cam[1]) * z + self.H / 2
        x1 = (r.right - self.cam[0]) * z + self.W / 2
        y1 = (r.bottom - self.cam[1]) * z + self.H / 2
        return pygame.Rect(round(x0), round(y0), round(x1) - round(x0), round(y1) - round(y0))

    def to_world(self, pos):
        return ((pos[0] - self.W / 2) / self.zoom + self.cam[0],
                (pos[1] - self.H / 2) / self.zoom + self.cam[1])

    def tile_rects(self):
        return [self.to_screen_rect(t) for t in self.tiles]

    def clamp_camera(self):
        """Keep the view on the bomb: centred when it fits, edge-to-edge when zoomed in."""
        bounds = self.grid_rect.inflate(2 * TILE_GAP + 80, 2 * TILE_GAP + 80)
        for axis, (lo, hi, half) in enumerate(((bounds.left, bounds.right, self.W / 2),
                                               (bounds.top, bounds.bottom, self.H / 2))):
            half /= self.zoom
            if hi - lo <= 2 * half:
                self.cam[axis] = (lo + hi) / 2
            else:
                self.cam[axis] = min(max(self.cam[axis], lo + half), hi - half)

    def zoom_at(self, pos, notches):
        anchor = self.to_world(pos)
        self.zoom = min(self.max_zoom, max(self.min_zoom, self.zoom * ZOOM_STEP ** notches))
        # Keep the world point under the cursor where it was.
        self.cam[0] = anchor[0] - (pos[0] - self.W / 2) / self.zoom
        self.cam[1] = anchor[1] - (pos[1] - self.H / 2) / self.zoom
        self.clamp_camera()

    # ---- visibility ----
    def book_visible(self):
        return self.book_anim > 0

    def light_visible(self):
        """Mirror the blue light in the HUD when its tile can't be fully seen."""
        if self.blue is None or self.blue.solved or self.state != "running":
            return False
        tile = self.tile_rects()[self.puzzles.index(self.blue)]
        return self.book_visible() or not self.screen.get_rect().contains(tile)

    def hud_timer_visible(self):
        tile = self.tile_rects()[CENTER]
        return self.book_visible() or not self.screen.get_rect().contains(tile)

    # ---- update ----
    def update(self):
        now = pygame.time.get_ticks()
        dt = now - self.last_ms
        self.last_ms = now
        step = dt / BOOK_ANIM_MS
        if self.book_open:
            self.book_anim = min(1.0, self.book_anim + step)
        else:
            self.book_anim = max(0.0, self.book_anim - step)

        if self.state == "running":
            for p in self.puzzles:
                if p is not None:
                    p.update(now)
                    if p.penalty_ms:
                        self.penalty_ms += p.penalty_ms
                        self.last_penalty = p.penalty_ms
                        self.penalty_at = now
                        p.penalty_ms = 0
            if self.remaining_ms() <= 0:
                self.frozen_remaining = 0
                self.state = "lost"
                self.end_round()
            elif self.all_solved():
                self.frozen_remaining = self.remaining_ms()
                self.defused_at = now
                self.state = "defused"
                self.zoom_from = (self.zoom, list(self.cam))
                self.end_round()
        elif self.state == "defused":
            # Ease back out to the whole bomb, then show the end screen.
            t = ease_out_cubic(min(1.0, (now - self.defused_at) / WIN_ZOOM_OUT_MS))
            z0, (x0, y0) = self.zoom_from
            self.zoom = z0 * (self.min_zoom / z0) ** t      # geometric, so it feels even
            self.cam = [x0 + (self.grid_rect.centerx - x0) * t,
                        y0 + (self.grid_rect.centery - y0) * t]
            if now - self.defused_at >= WIN_SCREEN_DELAY_MS:
                self.state = "won"

    def end_round(self):
        self.release_capture()
        self.pan_button = None
        self.book_open = False

    # ---- input ----
    def release_capture(self):
        """Drop whatever the player is dragging (as if released far off any target)."""
        if self.capture is not None:
            self.puzzles[self.capture].on_mouse_up((-10 ** 6, -10 ** 6), self.tile_rects()[self.capture])
            self.capture = None

    def set_book(self, held):
        """The rule book is up exactly while SPACE is held."""
        if held and self.state == "running" and not self.book_open:
            self.book_open = True
            self.release_capture()
            self.pan_button = None
        elif not held:
            self.book_open = False

    def on_key(self, event):
        if self.state == "running" and not self.book_open:
            for p in self.puzzles:
                if p is not None:
                    p.on_key(event)

    def on_wheel(self, pos, notches):
        if self.state == "running" and not self.book_visible():
            self.zoom_at(pos, notches)

    def on_mouse_down(self, pos, button):
        if self.state in ("won", "lost"):
            if button == 1 and self.redo_rect.collidepoint(pos):
                self.reset()
            return
        if self.state != "running" or button not in (1, 2, 3):
            return
        if button == 1 and self.light_visible() and self.light_rect.collidepoint(pos):
            self.blue.press()
            return
        if self.book_visible():
            return
        over_hud = self.hud_timer_visible() and self.hud_timer_rect.collidepoint(pos)
        if button in (1, 3) and not over_hud:
            for i, rect in enumerate(self.tile_rects()):
                p = self.puzzles[i]
                if p is not None and rect.collidepoint(pos):
                    if p.on_mouse_down(pos, rect, button):
                        if button == 1:
                            self.capture = i
                        return
                    break
        self.pan_button = button             # nothing grabbed: drag pans the view

    def on_mouse_up(self, pos, button):
        if button == 1 and self.capture is not None:
            self.puzzles[self.capture].on_mouse_up(pos, self.tile_rects()[self.capture])
            self.capture = None
        if button == self.pan_button:
            self.pan_button = None

    def on_mouse_motion(self, rel):
        if self.pan_button is not None:
            self.cam[0] -= rel[0] / self.zoom
            self.cam[1] -= rel[1] / self.zoom
            self.clamp_camera()

    # ---- drawing ----
    def draw(self):
        s = self.screen
        s.fill(BG)
        live = self.state == "running" and not self.book_visible()
        mouse = pygame.mouse.get_pos() if live else (-1, -1)
        screen_rect = s.get_rect()

        panel = self.to_screen_rect(self.grid_rect.inflate(TILE_GAP * 2, TILE_GAP * 2))
        pygame.draw.rect(s, PANEL, panel, border_radius=max(2, int(18 * self.zoom)))
        for i, rect in enumerate(self.tile_rects()):
            if not rect.colliderect(screen_rect):
                continue
            fonts = self.fonts_at(scale_of(rect))
            if i == CENTER:
                pygame.draw.rect(s, TIMER_TILE, rect, border_radius=max(2, int(36 * scale_of(rect))))
                self.draw_timer(rect, fonts["timer"], fonts["big"], below=True)
            else:
                self.puzzles[i].draw(s, rect, fonts, mouse)

        hint = "Scroll: zoom    Drag empty space / right-drag: pan    Hold SPACE: rule book    ESC: quit"
        img = self.small_font.render(hint, True, DIM)
        back = img.get_rect(bottomleft=(24, self.H - 18)).inflate(20, 10)
        pygame.draw.rect(s, BG, back, border_radius=8)
        s.blit(img, img.get_rect(center=back.center))

        if self.hud_timer_visible():
            pygame.draw.rect(s, TIMER_TILE, self.hud_timer_rect, border_radius=12)
            pygame.draw.rect(s, PANEL, self.hud_timer_rect, 2, border_radius=12)
            self.draw_timer(self.hud_timer_rect, self.hud_timer_font, self.font, below=False)
        if self.book_visible():
            self.draw_book()
        if self.light_visible():
            r = self.light_rect
            pygame.draw.rect(s, PANEL, r, border_radius=12)
            self.blue.draw_lamp(s, r.center, 38)
        if self.state == "won":
            self.draw_end_screen("BOMB DEFUSED", TIMER_DONE, pygame.mouse.get_pos())
        elif self.state == "lost":
            self.draw_end_screen("BOOM - GAME OVER", TIMER_RUNNING, pygame.mouse.get_pos())

    def draw_timer(self, rect, timer_font, note_font, below):
        s = self.screen
        ms = self.remaining_ms()
        text = f"{ms // 60000:02d}:{ms // 1000 % 60:02d}.{ms % 1000:03d}"
        color = TIMER_DONE if self.state in ("defused", "won") else TIMER_RUNNING
        img = timer_font.render(text, True, color)
        s.blit(img, img.get_rect(center=rect.center))
        if self.penalty_at is not None and pygame.time.get_ticks() - self.penalty_at < 1200:
            img = note_font.render(f"-{self.last_penalty // 1000} s", True, TIMER_RUNNING)
            if below:
                s.blit(img, img.get_rect(center=(rect.centerx, rect.centery + rect.h * 0.28)))
            else:
                s.blit(img, img.get_rect(midleft=(rect.right + 14, rect.centery)))

    def draw_book(self):
        s = self.screen
        t = ease_out_cubic(self.book_anim)
        shade = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
        shade.fill((10, 11, 15, int(200 * t)))
        s.blit(shade, (0, 0))

        top = self.hud_timer_rect.bottom + 16
        page = pygame.Rect(0, top, min(1100, self.W - 420), self.H - top - 20)
        page.centerx = self.W // 2
        page.y += round((1 - t) * (self.H - page.y + 20))     # slides up from below the screen
        pygame.draw.rect(s, BOOK_PAGE, page, border_radius=10)
        pygame.draw.line(s, (200, 190, 168), (page.centerx, page.y + 30),
                         (page.centerx, page.bottom - 30), 2)
        col_w = page.w // 2 - 70
        title = self.title_font.render("Defusal Manual", True, BOOK_ACCENT)
        s.blit(title, (page.x + 40, page.y + 20))

        # One section per module on this bomb (switches share one), in tile order.
        sections = [[("heading", "How to defuse"),
                     ("text", "Solve every module before the timer reaches zero. All modules "
                              "work at any zoom: scroll to zoom in, drag empty space or "
                              "right-drag to pan. The timer keeps running while this book is "
                              "open.")]]
        has_switch = False
        for i, p in enumerate(self.puzzles):
            if isinstance(p, SwitchPuzzle):
                has_switch = True
            elif p is not None:
                sections.append([("heading", f"{p.title}  ({POSITION_NAMES[i]})")]
                                + p.manual_general() + p.manual(POSITION_NAMES[i]))
        if has_switch:
            sections.append([("heading", "Switches")] + SwitchPuzzle.manual_general())

        # Flow whole sections down the left column, then the right; shrink the type
        # until everything fits on the page.
        columns = [(page.x + 40, page.y + 30 + title.get_height()), (page.centerx + 30, page.y + 24)]
        bottom = page.bottom - 40
        for size in BOOK_FONT_SIZES:
            body, heading = self.book_fonts[size]
            placed, col, y = [], 0, columns[0][1]
            for section in sections:
                h = self.draw_entries(section, 0, 0, col_w, body, heading, measure=True)
                if y + h > bottom and col + 1 < len(columns) and y > columns[col][1]:
                    col += 1
                    y = columns[col][1]
                placed.append((section, columns[col][0], y))
                y += h + 8
            if y <= bottom:
                break
        for section, x, y in placed:
            self.draw_entries(section, x, y, col_w, body, heading)

        img = self.small_font.render("Release SPACE to close", True, (120, 110, 95))
        s.blit(img, img.get_rect(bottomright=(page.right - 24, page.bottom - 14)))

    def draw_entries(self, entries, x, y, width, body, heading, measure=False):
        """Draw rule-book entries (or just measure them). Returns the height used."""
        s = self.screen
        top, rule_no = y, 0
        for kind, text in entries:
            if kind == "heading":
                if not measure:
                    s.blit(heading.render(text, True, BOOK_ACCENT), (x, y))
                y += heading.get_linesize() + 2
                rule_no = 0
                continue
            indent = 0
            if kind == "rule":
                rule_no += 1
                if not measure:
                    s.blit(body.render(f"{rule_no}.", True, BOOK_INK), (x, y))
                indent = 30
            for line in wrap_text(body, text, width - indent):
                if not measure:
                    s.blit(body.render(line, True, BOOK_INK), (x + indent, y))
                y += body.get_linesize()
            y += 6
        return y - top

    def draw_end_screen(self, title, title_color, mouse):
        s = self.screen
        shade = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
        shade.fill((10, 11, 15, 235))
        s.blit(shade, (0, 0))

        img = self.big_font.render(title, True, title_color)
        s.blit(img, img.get_rect(center=(self.W // 2, self.H // 2 - 80)))
        if self.state == "won":
            ms = self.frozen_remaining
            sub = f"Congratulations! Defused with {ms // 1000}.{ms % 1000:03d}s to spare"
            img = self.font.render(sub, True, TEXT)
            s.blit(img, img.get_rect(center=(self.W // 2, self.H // 2)))

        draw_button(s, self.redo_rect, "Redo", self.font, self.redo_rect.collidepoint(mouse))


def open_window():
    """Borderless desktop-sized window ("fake fullscreen").

    pygame.FULLSCREEN switches the monitor's display mode, which on Windows with
    display scaling resizes and rearranges every other application's windows.
    A borderless window covering the desktop looks the same without that.
    """
    os.environ["SDL_VIDEO_WINDOW_POS"] = "0,0"
    pygame.init()
    return pygame.display.set_mode(pygame.display.get_desktop_sizes()[0], pygame.NOFRAME)


def main():
    screen = open_window()
    pygame.display.set_caption("Bomb Defusal")
    clock = pygame.time.Clock()
    game = Game(screen)

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    pygame.quit()
                    sys.exit()
                elif event.key == pygame.K_SPACE:
                    game.set_book(True)
                else:
                    game.on_key(event)
            elif event.type == pygame.KEYUP and event.key == pygame.K_SPACE:
                game.set_book(False)
            elif event.type == pygame.WINDOWFOCUSLOST:
                game.set_book(False)          # the SPACE release may never arrive
            elif event.type == pygame.MOUSEWHEEL:
                game.on_wheel(pygame.mouse.get_pos(), event.precise_y or event.y)
            elif event.type == pygame.MOUSEBUTTONDOWN:
                game.on_mouse_down(event.pos, event.button)
            elif event.type == pygame.MOUSEBUTTONUP:
                game.on_mouse_up(event.pos, event.button)
            elif event.type == pygame.MOUSEMOTION:
                game.on_mouse_motion(event.rel)

        game.update()
        game.draw()
        pygame.display.flip()
        clock.tick(FPS)


if __name__ == "__main__":
    main()
