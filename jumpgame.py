"""
LEAP RUNNER - a charge-and-jump platformer made with pygame.

HOW TO PLAY
  * Hold the JUMP button (bottom-right) with the mouse, or hold SPACE,
    to charge your jump. Release to leap. Longer hold = farther and higher.
  * Clear pits, liquids and obstacles. Touching a hazard ends the attempt.
  * A / D or LEFT / RIGHT shuffle a few steps (and turn around).
  * ESC pauses / goes back.

MODES
  * Levels  - 7 biomes x 5 hand-checked levels. Beat a level to unlock the next.
              Dying restarts the level. Every level is pregenerated (fixed layout).
  * Sandbox - endless and randomly generated. You stay in a biome for ~400 m,
              then switch to a random new one. Play with or without checkpoints.

BIOMES & MECHANICS
  Meadow (classic) - Desert (rolling tumbleweeds) - Mountains (slippery ice,
  falling icicles) - Jungle (grabbable vines, crocodiles) - Moon (low gravity,
  bounce pads) - Volcano (fire geysers, heat updrafts) - Sky Islands (wind,
  bounce clouds, moving platforms).

FILES
  leap_runner_levels.json  - the pregenerated levels (keep it next to this file).
  leap_runner_save.json    - your progress (created automatically).
  Rebuild & re-verify the levels:  python leap_runner.py --build-levels
  Owner's secret: click Cheats on the title screen and enter  strawberry
  to unlock every level,  blueberry  to fake focus levels 1-5 (5 = most focused = easiest),
  or  compost  to turn every cheat off again (levels you beat stay beaten).

Requires: pip install pygame
"""
import bisect
import json
import math
import os
import random
import sys

# ================================================================ constants
W, H = 960, 540
FPS = 60
GROUND_Y = 400
PPM = 20                      # pixels per metre
CHARGE_FRAMES = 66            # frames to reach full power (~1.1 s)
MIN_VX, MAX_VX = 3.0, 12.0
MIN_VY, MAX_VY = 6.0, 14.0
WALK_SPEED = 2.6
PHW, PH = 11, 50              # player half-width / height
FLIP_THRESHOLD = 0.7
PAD_VX, PAD_VY, PAD_W = 6.5, 12.0, 56
PAD_STRENGTH = {"moon": (11.0, 13.0)}   # moon pads launch ~1000 px; other biomes use PAD_VX/PAD_VY
VINE_GAP_OPTIONAL = (500, 580)   # jumpable without the vine, but needs ~80-90% charge
VINE_GAP_REQUIRED = (760, 850)   # longer than a full jump (672 px): you must use the vine
MOON_PAD_GAP_OPTIONAL = (600, 700)   # moon full jump is 816 px; needs ~80-90% charge
MOON_PAD_REQUIRED_MARGIN = 110       # required pad gaps end this far before the pad's landing spot
VINE_BOTTOM = GROUND_Y - 110
HANG_DROP = 48
LIFT = 0.32
WIND_POWER = 0.05
ICE_SLIDE_FRAMES = 54                   # ice slides you to the edge in 0.9 s, speeding up
VINE_LATCH_RADIUS = 40                  # how close you must be when you press to latch onto a vine
START_X = 160
SECRET_CODE = "strawberry"    # enter this on the Cheats screen to unlock every level
RESET_CODE = "compost"        # enter this on the Cheats screen to turn every cheat off (real progress is kept)
FOCUS_CODE = "blueberry"      # toggles a Focus box in game: type 1-5 to fake your brain's focus level
# Focus 1 = distracted (hardest) ... 5 = most focused (easiest). Charging always takes the same
# 1.1 s, so focusing never costs time. Higher focus shows more of the jump arc; low focus makes the
# power meter wobble (your jump uses whatever the meter shows the moment you let go).
FOCUS_WOBBLE = {1: 0.09, 2: 0.04, 3: 0.0, 4: 0.0, 5: 0.0}   # +/- share of full power
FOCUS_WOBBLE_SPEED = 0.35                                    # radians per frame (~3 wobbles/sec)
FOCUS_PREVIEW = {1: 0.1, 2: 0.18, 3: 0.32, 4: 0.6, 5: 1.0}   # focus 1 still shows a stub so the wobble is visible   # how much of the jump arc is previewed
LEVEL_LENGTHS_M = [200, 275, 350, 425, 500]
SECTION_PX = 400 * PPM
CHECKPOINT_PX = 250 * PPM
FOCUS_COLORS = {1: (240, 80, 70), 2: (245, 150, 60), 3: (240, 220, 80), 4: (120, 210, 255), 5: (110, 255, 170)}
HERE = os.path.dirname(os.path.abspath(__file__))
SAVE_PATH = os.path.join(HERE, "leap_runner_save.json")
LEVELS_PATH = os.path.join(HERE, "leap_runner_levels.json")
LEVELS_VERSION = 5           # bump whenever level generation changes; old files rebuild automatically

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
TEXT_DARK = (35, 40, 60)

# ================================================================ biomes
BIOMES = [
    dict(key="meadow", name="Meadow", blurb="Pits, ponds and the classic obstacles",
         sky=((105, 175, 255), (205, 238, 255)), hills="round",
         hill_far=(150, 200, 170), hill_near=(110, 175, 120),
         top=(92, 196, 84), top_dark=(62, 150, 62), dirt=(152, 102, 62), dirt_dark=(112, 74, 44),
         pit=(22, 18, 28), gap="pit", liquid="water", rock=(120, 120, 130), spike=(200, 205, 215),
         celestial="sun", clouds=True, tufts=True, ambient=None,
         gravity=0.5, jscale=(1.0, 1.0), obstacles=["rock", "crate", "spikes"]),
    dict(key="desert", name="Desert", blurb="Time your jumps over rolling tumbleweeds",
         sky=((255, 176, 110), (255, 232, 186)), hills="dunes",
         hill_far=(236, 196, 132), hill_near=(222, 172, 104),
         top=(240, 210, 140), top_dark=(214, 178, 108), dirt=(208, 158, 94), dirt_dark=(166, 118, 68),
         pit=(60, 36, 22), gap="pit", liquid="quicksand", rock=(196, 128, 84), spike=(200, 190, 170),
         celestial="bigsun", clouds=False, tufts=False, ambient="sand",
         gravity=0.5, jscale=(1.0, 1.0), obstacles=["cactus", "rock"]),
    dict(key="mountains", name="Mountains", blurb="Slippery ice and falling icicles",
         sky=((118, 158, 210), (226, 236, 250)), hills="peaks",
         hill_far=(168, 184, 210), hill_near=(128, 148, 180),
         top=(246, 250, 255), top_dark=(198, 214, 236), dirt=(118, 120, 136), dirt_dark=(86, 88, 104),
         pit=(18, 26, 46), gap="pit", liquid="icewater", rock=(110, 116, 130), spike=(190, 230, 255),
         celestial="palesun", clouds=True, tufts=False, ambient="snow",
         gravity=0.5, jscale=(1.0, 1.0), obstacles=["rock", "icespikes"]),
    dict(key="jungle", name="Jungle", blurb="Grab vines mid-air, dodge crocodiles",
         sky=((86, 166, 140), (192, 232, 202)), hills="trees",
         hill_far=(70, 140, 92), hill_near=(36, 108, 58),
         top=(62, 164, 60), top_dark=(36, 116, 40), dirt=(96, 70, 44), dirt_dark=(64, 46, 28),
         pit=(16, 24, 14), gap="pit", liquid="swamp", rock=(96, 112, 96), spike=(40, 90, 40),
         celestial="sun", clouds=True, tufts=True, ambient="fireflies",
         gravity=0.5, jscale=(1.0, 1.0), obstacles=["thorns", "rock"]),
    dict(key="moon", name="The Moon", blurb="Low gravity and bounce pads",
         sky=((8, 8, 26), (40, 40, 72)), hills="moon",
         hill_far=(86, 86, 104), hill_near=(66, 66, 82),
         top=(204, 204, 214), top_dark=(160, 160, 176), dirt=(132, 132, 148), dirt_dark=(98, 98, 114),
         pit=(4, 4, 10), gap="pit", liquid=None, rock=(150, 150, 165), spike=(160, 120, 240),
         celestial="earth", clouds=False, tufts=False, ambient=None,
         gravity=0.28, jscale=(0.85, 0.8), obstacles=["rock", "crystals"]),
    dict(key="volcano", name="Volcano", blurb="Lava, fire geysers and heat updrafts",
         sky=((54, 18, 24), (176, 72, 40)), hills="volcano",
         hill_far=(84, 40, 42), hill_near=(56, 30, 32),
         top=(74, 62, 62), top_dark=(46, 38, 38), dirt=(62, 46, 46), dirt_dark=(40, 30, 30),
         pit=(20, 6, 6), gap="pit", liquid="lava", rock=(52, 40, 62), spike=(70, 60, 80),
         celestial="redsun", clouds=False, tufts=False, ambient="embers",
         gravity=0.5, jscale=(1.0, 1.0), obstacles=["rock", "spikes"]),
    dict(key="sky", name="Sky Islands", blurb="Wind, bounce clouds and moving platforms",
         sky=((92, 160, 255), (255, 222, 236)), hills="sky",
         hill_far=(255, 255, 255), hill_near=(240, 246, 255),
         top=(120, 212, 110), top_dark=(80, 166, 80), dirt=(166, 122, 86), dirt_dark=(122, 86, 58),
         pit=(0, 0, 0), gap="sky", liquid=None, rock=(140, 140, 150), spike=(210, 214, 226),
         celestial="sun", clouds=True, tufts=True, ambient=None,
         gravity=0.5, jscale=(1.0, 1.0), obstacles=["crate", "spikes"]),
]
BIOME_BY_KEY = {b["key"]: b for b in BIOMES}

LIQUIDS = {
    "water": dict(color=(40, 120, 220), light=(140, 200, 255), alpha=215, name="the water"),
    "quicksand": dict(color=(196, 150, 80), light=(232, 196, 130), alpha=255, name="quicksand"),
    "icewater": dict(color=(70, 150, 210), light=(205, 238, 255), alpha=220, name="freezing water"),
    "swamp": dict(color=(66, 100, 52), light=(140, 176, 92), alpha=235, name="the swamp"),
    "lava": dict(color=(236, 78, 20), light=(255, 204, 64), alpha=255, name="lava"),
}

OBSTACLE_NAMES = {"rock": "a rock", "crate": "a crate", "spikes": "spikes", "icespikes": "ice spikes",
                  "cactus": "a cactus", "thorns": "a thorn bush", "crystals": "sharp crystals"}


# ================================================================ helpers
def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def lerp_color(a, b, t):
    t = clamp(t, 0.0, 1.0)
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def h01(*args):
    """Deterministic pseudo-random value in [0, 1] from integers."""
    v = 2166136261
    for a in args:
        v = ((v ^ (int(a) & 0xFFFFFFFF)) * 16777619) & 0xFFFFFFFF
    v ^= v >> 13
    v = (v * 1274126177) & 0xFFFFFFFF
    v ^= v >> 16
    return v / 4294967295.0


def rect_hit(ax, ay, aw, ah, bx, by, bw, bh):
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def jump_velocity(charge):
    """Map a 0..1 charge to (horizontal speed, upward speed)."""
    return (MIN_VX + (MAX_VX - MIN_VX) * charge,
            MIN_VY + (MAX_VY - MIN_VY) * charge)


def charge_of(frames):
    return min(1.0, frames / CHARGE_FRAMES)


def biome_phys(key):
    b = BIOME_BY_KEY.get(key, BIOMES[0])
    return b["gravity"], b["jscale"]


def pad_vel(biome):
    return PAD_STRENGTH.get(biome, (PAD_VX, PAD_VY))


def plat_x(p, t):
    return p["cx"] + p["amp"] * math.sin(t * 2 * math.pi / p["period"] + p["phase"])


def vine_bx(v, t):
    return v["x"] + 10 * math.sin(t * 0.03 + v["phase"])


# ================================================================ world (pure python)
class Seg:
    __slots__ = ("kind", "x0", "x1", "biome", "liquid", "tag")

    def __init__(self, kind, x0, x1, biome, liquid=None, tag=None):
        self.kind, self.x0, self.x1, self.biome, self.liquid, self.tag = kind, x0, x1, biome, liquid, tag


def obstacle_hitbox(kind, x, w, h):
    s = {"crate": 2, "cactus": 4}.get(kind, 6)
    return (x + s, GROUND_Y - h + s, w - 2 * s, h - s)


class World:
    """Level geometry + physics queries. Shared by the game and the level checker."""
    B = 256

    def __init__(self):
        self.segments, self.obstacles, self.ice, self.ents = [], [], [], []
        self.pending = []
        self.end_x = 0
        self._clear_index()

    # ---------- indexing
    def _clear_index(self):
        self.b_seg, self.b_obs, self.b_ice, self.b_wind, self.b_lift = {}, {}, {}, {}, {}
        self.b_vine, self.b_croc, self.b_pad, self.b_plat = {}, {}, {}, {}

    def _put(self, store, x0, x1, item):
        for k in range(int(math.floor(x0 / self.B)), int(math.floor(x1 / self.B)) + 1):
            store.setdefault(k, []).append(item)

    def _get(self, store, x):
        return store.get(int(math.floor(x / self.B)), ())

    def _index_ent(self, d):
        t = d["t"]
        if t == "wind":
            self._put(self.b_wind, d["x0"], d["x1"], d)
        elif t == "updraft":
            self._put(self.b_lift, d["x0"], d["x1"], d)
        elif t == "vine":
            self._put(self.b_vine, d["x"] - 60, d["x"] + 60, d)
        elif t == "croc":
            self._put(self.b_croc, d["x"] - 60, d["x"] + 60, d)
        elif t == "pad":
            self._put(self.b_pad, d["x"] - 60, d["x"] + 60, d)
        elif t == "platform":
            self._put(self.b_plat, d["cx"] - d["amp"] - d["w"], d["cx"] + d["amp"] + d["w"], d)

    # ---------- building
    def add_segment(self, kind, x0, x1, biome, liquid=None, tag=None):
        s = Seg(kind, x0, x1, biome, liquid, tag)
        self.segments.append(s)
        self._put(self.b_seg, x0, x1, s)
        self.end_x = max(self.end_x, x1)
        return s

    def add_obstacle(self, kind, x, w, h, biome):
        ob = dict(kind=kind, x=x, w=w, h=h, biome=biome, hb=obstacle_hitbox(kind, x, w, h))
        self.obstacles.append(ob)
        self._put(self.b_obs, x - 20, x + w + 20, ob)
        return ob

    def add_ice(self, x0, x1):
        z = [x0, x1]
        self.ice.append(z)
        self._put(self.b_ice, x0, x1, z)

    def add_ent(self, d):
        self.ents.append(d)
        self.pending.append(d)
        self._index_ent(d)
        return d

    def prune(self, min_x):
        self.segments = [s for s in self.segments if s.x1 > min_x]
        self.obstacles = [o for o in self.obstacles if o["x"] + o["w"] > min_x]
        self.ice = [z for z in self.ice if z[1] > min_x]
        self.ents = [d for d in self.ents if ent_right(d) > min_x]
        self._clear_index()
        for s in self.segments:
            self._put(self.b_seg, s.x0, s.x1, s)
        for o in self.obstacles:
            self._put(self.b_obs, o["x"] - 20, o["x"] + o["w"] + 20, o)
        for z in self.ice:
            self._put(self.b_ice, z[0], z[1], z)
        for d in self.ents:
            self._index_ent(d)

    # ---------- serialisation
    def to_data(self):
        return dict(segments=[[s.kind, s.x0, s.x1, s.biome, s.liquid] for s in self.segments],
                    obstacles=[[o["kind"], o["x"], o["w"], o["h"], o["biome"]] for o in self.obstacles],
                    ice=[list(z) for z in self.ice], ents=self.ents)

    @classmethod
    def from_data(cls, data):
        w = cls()
        for k, x0, x1, b, liq in data["segments"]:
            w.add_segment(k, x0, x1, b, liq)
        for k, x, ww, hh, b in data["obstacles"]:
            w.add_obstacle(k, x, ww, hh, b)
        for x0, x1 in data["ice"]:
            w.add_ice(x0, x1)
        for d in data["ents"]:
            w.add_ent(dict(d))
        return w

    # ---------- queries
    def segment_at(self, x):
        for s in self._get(self.b_seg, x):
            if s.x0 <= x < s.x1:
                return s
        return None

    def biome_at(self, x):
        s = self.segment_at(x)
        if s:
            return s.biome
        return self.segments[-1].biome if self.segments else "meadow"

    def obstacle_hit(self, x, y):
        px, py = x - PHW, y - PH
        for ob in self._get(self.b_obs, x):
            hx, hy, hw, hh = ob["hb"]
            if rect_hit(px, py, PHW * 2, PH, hx, hy, hw, hh):
                return ob
        return None

    def ice_at(self, x):
        for z in self._get(self.b_ice, x):
            if z[0] <= x < z[1]:
                return True
        return False

    def wind_at(self, x):
        a = 0.0
        for d in self._get(self.b_wind, x):
            if d["x0"] <= x < d["x1"]:
                a += d["dir"] * WIND_POWER
        return a

    def lift_at(self, x, y):
        if y < GROUND_Y - 300:
            return 0.0
        for d in self._get(self.b_lift, x):
            if d["x0"] <= x < d["x1"]:
                return LIFT
        return 0.0

    def vine_grab(self, x, y, t, exclude=None, radius=16):
        for v in self._get(self.b_vine, x):
            if v is exclude:
                continue
            if abs(x - vine_bx(v, t)) < radius and y - PH < VINE_BOTTOM:
                return v
        return None

    def croc_zone_hit(self, x, y):
        for c in self._get(self.b_croc, x):
            if rect_hit(x - PHW, y - PH, PHW * 2, PH, c["x"] - 32, GROUND_Y - 78, 64, 98):
                return True
        return False

    def pad_at(self, x):
        for p in self._get(self.b_pad, x):
            if abs(x - p["x"]) < PAD_W / 2:
                return p
        return None

    def plat_at(self, x, t):
        for p in self._get(self.b_plat, x):
            if abs(x - plat_x(p, t)) <= p["w"] / 2:
                return p
        return None

    def support_at(self, x, t):
        s = self.segment_at(x)
        if s is not None and s.kind == "ground":
            return ("ground", s)
        p = self.plat_at(x, t)
        if p is not None:
            return ("plat", p)
        return None


def ent_right(d):
    t = d["t"]
    if "x1" in d:
        return d["x1"]
    if t == "platform":
        return d["cx"] + d["amp"] + d["w"]
    return d.get("x", 0) + 200


# ================================================================ shared physics
class Body:
    __slots__ = ("x", "y", "vx", "vy", "g")

    def __init__(self, x, y, vx, vy, g):
        self.x, self.y, self.vx, self.vy, self.g = x, y, vx, vy, g


def air_step(world, b, t, exclude=None, static_crocs=False, can_grab=True):
    """Advance an airborne body one frame. Returns None or an event tuple.
    The level checker uses can_grab=True (it assumes the player presses to latch);
    the game passes False and handles latching itself when the player presses."""
    ax = world.wind_at(b.x)
    lift = world.lift_at(b.x, b.y)
    b.vx += ax
    b.vy += b.g - lift
    b.x += b.vx
    b.y += b.vy
    v = world.vine_grab(b.x, b.y, t, exclude) if can_grab else None
    if v is not None:
        return ("vine", v)
    ob = world.obstacle_hit(b.x, b.y)
    if ob is not None:
        return ("crash", ob)
    if static_crocs and world.croc_zone_hit(b.x, b.y):
        return ("croc", None)
    if b.vy > 0 and b.y >= GROUND_Y:
        sup = world.support_at(b.x, t)
        if sup is not None:
            return ("land", sup)
        return ("fall", world.segment_at(b.x))
    if b.y > H + 300:
        return ("fall", None)
    return None


def ice_slide_target(world, x):
    """Ice never lets go: you slide right off the end of the ledge."""
    seg = world.segment_at(x)
    return (seg.x1 if seg is not None else x) + 3


def slide_result(world, x, vx_land=0.0):
    """Where you end up after landing at x. Landing on ice counts as a fall for the
    level checker, so every level can be beaten without touching ice."""
    return None if world.ice_at(x) else x


# ================================================================ generation
def level_cfg(bi, lvl):
    """Difficulty settings for biome index bi, level 1..5."""
    b = BIOMES[bi]
    key = b["key"]
    g = lvl - 1
    c = dict(hmin=60 + 12 * g, hmax=min(300, 135 + 34 * g + 6 * bi),
             gmin=max(230, 370 - 28 * g - 4 * bi), gmax=540 - 22 * g,
             liquid=0.45 if b["liquid"] else 0.0,
             obstacle=[0.2, 0.25, 0.3, 0.45, 0.55][g], kinds=list(b["obstacles"]), stack=False,
             tumble=0.0, tumble_speed=(1.5, 2.0), tumble_pairs=0.0,
             ice=0.0, ice_full=0.0, icicle=0.0, vine=0.0, croc=0.0, pad=0.0,
             geyser=0.0, updraft=0.0, wind=0.0, platform=0.0)
    if key == "meadow":
        c["hmax"] = [140, 180, 220, 260, 300][g]
        c["liquid"] = 0.0 if g == 0 else 0.45
        c["obstacle"] = [0, 0, 0.35, 0.55, 0.7][g]
        c["kinds"] = [[], [], ["rock", "crate"], ["rock", "crate", "spikes"], ["rock", "crate", "spikes"]][g]
        c["stack"] = g == 4
        c["gmin"] = [380, 340, 320, 280, 240][g]
    elif key == "desert":
        c["tumble"] = [0, 0.3, 0.35, 0.4, 0.42][g]
        c["tumble_speed"] = [(1.4, 1.9), (1.4, 1.9), (1.8, 2.4), (2.0, 2.7), (2.2, 2.9)][g]
        c["tumble_pairs"] = [0, 0, 0, 0.35, 0.5][g]
    elif key == "mountains":
        c["ice"] = [0, 0.5, 0.45, 0.5, 0.55][g]
        c["ice_full"] = 0.0   # ice only ever sits on the right edge of a ledge
        c["icicle"] = [0, 0, 0.25, 0.25, 0.3][g]
    elif key == "jungle":
        c["liquid"] = 0.55
        c["vine"] = [0, 0.25, 0.15, 0.25, 0.25][g]
        c["vine_req"] = [0, 0.25, 0.35, 0.45, 0.5][g]
        c["croc"] = [0, 0, 0.55, 0.55, 0.6][g]
    elif key == "moon":
        c["pad"] = [0, 0.3, 0.3, 0.35, 0.35][g]
        c["pad_req"] = [0, 0.25, 0.35, 0.45, 0.5][g]
        c["hmin"] = int(c["hmin"] * 1.3)
        c["hmax"] = int(c["hmax"] * 1.3)
    elif key == "volcano":
        c["liquid"] = 0.55
        c["geyser"] = [0, 0.3, 0.25, 0.3, 0.35][g]
        c["updraft"] = [0, 0, 0.2, 0.18, 0.22][g]
    elif key == "sky":
        c["pad"] = [0.3, 0.15, 0.15, 0.18, 0.2][g]
        c["wind"] = [0, 0.4, 0.3, 0.4, 0.45][g]
        c["platform"] = [0, 0, 0.18, 0.15, 0.18][g]
        c["stack"] = g >= 3
    return c


def obstacle_size(kind, rng, stack_ok):
    if kind == "rock":
        return rng.randint(40, 60), rng.randint(30, 52)
    if kind == "crate":
        w = rng.choice([40, 46])
        return w, (w * 2 if stack_ok and rng.random() < 0.5 else w)
    if kind in ("spikes", "icespikes"):
        return rng.choice([48, 72, 96]), (26 if kind == "spikes" else 30)
    if kind == "cactus":
        return rng.randint(30, 36), rng.randint(48, 68)
    if kind == "thorns":
        return rng.randint(56, 84), rng.randint(28, 34)
    if kind == "crystals":
        return rng.randint(40, 64), rng.randint(30, 40)
    return 40, 40


class Generator:
    def __init__(self, world, rng):
        self.w, self.rng = world, rng
        self.last_ground = None
        self.seen = {}   # mechanics already shown in this level (first one is always optional)

    def ground(self, biome, x0, x1, tag=None):
        s = self.w.add_segment("ground", x0, x1, biome, tag=tag)
        self.last_ground = s
        return s

    def start(self, biome):
        return self.ground(biome, -600, 480, "plain")

    def safe(self, biome, length):
        x0 = self.w.end_x
        return self.ground(biome, x0, x0 + length, "plain")

    def step(self, key, cfg):
        rng, w = self.rng, self.w
        b = BIOME_BY_KEY[key]
        liquid = b["liquid"]
        g, _js = biome_phys(key)
        prev = self.last_ground
        x0 = w.end_x
        feat = "normal"
        prev_len = prev.x1 - prev.x0
        if cfg["platform"] and rng.random() < cfg["platform"]:
            feat = "platform"
        elif cfg["vine"] and rng.random() < cfg["vine"]:
            feat = "vine"
        elif (cfg["pad"] and rng.random() < cfg["pad"] and prev_len >= 260
              and prev.tag in (None, "plain") and prev.biome == key):
            feat = "pad"
        elif cfg["updraft"] and rng.random() < cfg["updraft"]:
            feat = "updraft"

        def pick_kind(force_liquid=False):
            if liquid and (force_liquid or rng.random() < cfg["liquid"]):
                return "liquid"
            return "gap"

        if feat == "normal":
            width = rng.randint(cfg["hmin"], cfg["hmax"])
            kind = pick_kind()
            if cfg["wind"] and rng.random() < cfg["wind"]:
                d = rng.choice([-1, 1])
                if d < 0:
                    width = min(width, int(cfg["hmax"] * 0.75))
                w.add_ent(dict(t="wind", x0=x0 - 30, x1=x0 + width + 30, dir=d))
            if kind == "liquid" and liquid == "swamp" and rng.random() < cfg["croc"]:
                width = max(width, 180)
                w.add_ent(dict(t="croc", x=x0 + width // 2))
        elif feat == "platform":
            width = rng.randint(430, 520)
            kind = pick_kind()
            w.add_ent(dict(t="platform", cx=x0 + width // 2, amp=rng.randint(50, 80), w=110,
                           period=rng.randint(220, 320), phase=round(rng.random() * 6.283, 3)))
        elif feat == "vine":
            req = self.seen.get("vine", 0) > 0 and rng.random() < cfg.get("vine_req", 0)
            width = rng.randint(*(VINE_GAP_REQUIRED if req else VINE_GAP_OPTIONAL))
            kind = "liquid" if liquid and rng.random() < 0.5 else "gap"
            w.add_ent(dict(t="vine", x=x0 + width // 2, phase=round(rng.random() * 6.283, 3), req=req))
            self.seen["vine"] = self.seen.get("vine", 0) + 1
        elif feat == "pad":
            padx = prev.x1 - 45
            pvx, pvy = pad_vel(key)
            dist = 2 * pvx * pvy / g
            landing = padx + dist
            req = False
            if key == "moon":
                req = self.seen.get("pad", 0) > 0 and rng.random() < cfg.get("pad_req", 0)
                if req:
                    width = int(landing - MOON_PAD_REQUIRED_MARGIN - x0)
                else:
                    width = rng.randint(*MOON_PAD_GAP_OPTIONAL)
            else:
                width = max(60, int(landing - 160 - x0))
            w.add_ent(dict(t="pad", x=padx, req=req))
            prev.tag = "pad"
            self.seen["pad"] = self.seen.get("pad", 0) + 1
            kind = pick_kind()
        else:  # updraft
            width = rng.randint(360, 460)
            kind = pick_kind(force_liquid=True)
            w.add_ent(dict(t="updraft", x0=x0 + int(width * 0.2), x1=x0 + int(width * 0.8)))

        w.add_segment(kind, x0, x0 + width, key, liquid if kind == "liquid" else None)
        gx0 = x0 + width
        length = rng.randint(cfg["gmin"], cfg["gmax"])
        plain = False
        if feat != "normal":
            length = max(length, 400 if feat == "pad" else 380)
            if feat == "pad":
                length = max(length, int(landing - gx0) + 220)   # room to land after the bounce
            plain = True
        content = None
        if not plain:
            if cfg["tumble"] and rng.random() < cfg["tumble"]:
                content, length = "tumble", max(length, 460)
            elif cfg["geyser"] and rng.random() < cfg["geyser"]:
                content, length = "geyser", max(length, 400)
            elif cfg["icicle"] and rng.random() < cfg["icicle"]:
                content, length = "icicle", max(length, 380)
        seg = self.ground(key, gx0, gx0 + length, "plain" if plain else None)
        if not plain:
            self.decorate(seg, key, cfg, content)

    def decorate(self, seg, key, cfg, content):
        rng, w = self.rng, self.w
        L = seg.x1 - seg.x0
        if content == "tumble":
            w.add_ent(dict(t="tumble", x=seg.x1 - 20, x0=seg.x0,
                           speed=round(rng.uniform(*cfg["tumble_speed"]), 2),
                           interval=rng.randint(150, 220), pair=rng.random() < cfg["tumble_pairs"]))
            seg.tag = "tumble"
            return
        if content == "geyser":
            w.add_ent(dict(t="geyser", x=int(seg.x0 + L * rng.uniform(0.4, 0.6)), phase=rng.randint(0, 199)))
            seg.tag = "geyser"
            return
        has_ob = False
        if content != "icicle" and cfg["obstacle"] and cfg["kinds"] and L >= 340 and rng.random() < cfg["obstacle"]:
            kind = rng.choice(cfg["kinds"])
            ow, oh = obstacle_size(kind, rng, cfg["stack"] and L >= 400)
            cx = seg.x0 + L * rng.uniform(0.42, 0.58)
            w.add_obstacle(kind, int(cx - ow / 2), ow, oh, key)
            has_ob = True
        if not has_ob and cfg["ice"] and L >= 300 and rng.random() < cfg["ice"]:
            if cfg["ice_full"] and rng.random() < cfg["ice_full"]:
                w.add_ice(seg.x0 + 4, seg.x1 - 4)
                seg.tag = "ice"
            else:
                # ice sits on the far ledge, right before the next gap
                w.add_ice(seg.x1 - rng.randint(100, 170), seg.x1 - 4)
        if content == "icicle":
            w.add_ent(dict(t="icicle", x=int(seg.x0 + L * rng.uniform(0.5, 0.7))))


def build_level(bi, lvl, seed):
    """Generate one level. Returns (world, finish_x)."""
    rng = random.Random(seed)
    w = World()
    gen = Generator(w, rng)
    key = BIOMES[bi]["key"]
    cfg = level_cfg(bi, lvl)
    gen.start(key)
    target = START_X + LEVEL_LENGTHS_M[lvl - 1] * PPM
    while w.end_x < target:
        gen.step(key, cfg)
    fin = gen.safe(key, 760)
    finish_x = fin.x0 + 220
    w.add_ent(dict(t="finish", x=finish_x))
    return w, finish_x


class EndlessGen:
    """Random sandbox world: a random biome for ~400 m, then switch."""

    def __init__(self, world, rng, checkpoints):
        self.w, self.rng, self.cp = world, rng, checkpoints
        self.gen = Generator(world, rng)
        self.section = 0
        self.biome = rng.choice(BIOMES)["key"]
        self.gen.start(self.biome)
        world.add_ent(dict(t="sign", x=300, biome=self.biome))
        self.section_end = world.end_x + SECTION_PX
        self.next_cp = START_X + CHECKPOINT_PX

    def cfg(self):
        bi = [b["key"] for b in BIOMES].index(self.biome)
        return level_cfg(bi, min(5, 2 + self.section))

    def ensure(self, until):
        w = self.w
        while w.end_x < until:
            if w.end_x >= self.section_end:
                choices = [b["key"] for b in BIOMES if b["key"] != self.biome]
                self.biome = self.rng.choice(choices)
                self.section += 1
                seg = self.gen.safe(self.biome, 520)
                w.add_ent(dict(t="sign", x=seg.x0 + 120, biome=self.biome))
                if self.cp:
                    w.add_ent(dict(t="checkpoint", x=seg.x0 + 330))
                    self.next_cp = seg.x0 + 330 + CHECKPOINT_PX
                self.section_end = w.end_x + SECTION_PX
            elif self.cp and w.end_x >= self.next_cp:
                seg = self.gen.safe(self.biome, 380)
                w.add_ent(dict(t="checkpoint", x=seg.x0 + 190))
                self.next_cp = seg.x0 + 190 + CHECKPOINT_PX
            else:
                self.gen.step(self.biome, self.cfg())


# ================================================================ level checker
def build_intervals(world):
    ivs = []
    for s in world.segments:
        if s.kind != "ground":
            continue
        blocks = []
        for ob in world.obstacles:
            hx, hy, hw, hh = ob["hb"]
            if hx + hw > s.x0 and hx < s.x1:
                blocks.append((hx - PHW - 1, hx + hw + PHW + 1))
        for d in world.ents:
            if d["t"] == "pad" and s.x0 <= d["x"] < s.x1:
                blocks.append((d["x"] - PAD_W / 2 - 1, d["x"] + PAD_W / 2 + 1))
        for z0, z1 in world.ice:
            if z1 > s.x0 and z0 < s.x1:
                blocks.append((z0 - 1, z1 + 1))   # can't stand on ice
        blocks.sort()
        lo = s.x0 + 1
        for b0, b1 in blocks:
            if b0 > lo:
                ivs.append((lo, b0))
            lo = max(lo, b1)
        if s.x1 - 1 > lo:
            ivs.append((lo, s.x1 - 1))
    ivs.sort()
    return ivs


def solve(world, start_x, goal_x, req, tick=None):
    """Breadth-first search over standing spots using the real jump physics.
    An edge only counts if a run of at least `req` consecutive charge frames
    works, so every required jump has a comfortable timing window."""
    ivs = build_intervals(world)
    los = [a for a, _ in ivs]
    plats = {id(d): d for d in world.ents if d["t"] == "platform"}
    vines = {id(d): d for d in world.ents if d["t"] == "vine"}

    def iv_index(x):
        i = bisect.bisect_right(los, x) - 1
        if i >= 0 and ivs[i][0] <= x <= ivs[i][1]:
            return i
        return None

    def fly(b, t, exclude, depth):
        for _ in range(700):
            t += 1
            ev = air_step(world, b, t, exclude, static_crocs=True)
            if ev is None:
                continue
            if ev[0] == "land":
                sup = ev[1]
                if sup[0] == "plat":
                    return ("P", id(sup[1]))
                return landed(b.x, b.vx, t, depth)
            if ev[0] == "vine":
                return ("V", id(ev[1]))
            return None
        return None

    def landed(x, vx, t, depth):
        p = world.pad_at(x)
        if p is not None:
            if depth > 3:
                return None
            return bounce(x, t, depth + 1)
        fx = slide_result(world, x, vx)
        if fx is None:
            return None
        i = iv_index(fx)
        return ("I", i) if i is not None else None

    def bounce(x, t, depth):
        g, _ = biome_phys(world.biome_at(x))
        pvx, pvy = pad_vel(world.biome_at(x))
        return fly(Body(x, GROUND_Y, pvx, -pvy, g), t, None, depth)

    def try_jumps(x, y, t0, g, js, exclude, edges):
        results = []
        for k in range(CHARGE_FRAMES + 1):
            vx, vy = jump_velocity(charge_of(k))
            results.append(fly(Body(x, y, vx * js[0], -vy * js[1], g), t0, exclude, 0))
        run, prev = 0, None
        for r in results + [None]:
            if r is not None and r == prev:
                run += 1
            else:
                if prev is not None and run >= req:
                    edges.add(prev)
                run, prev = 1, r

    def near_moving(x0, x1):
        for d in world.ents:
            if d["t"] == "platform" and x0 - 200 < d["cx"] < x1 + 1000:
                return 0
            if d["t"] == "vine" and x0 - 200 < d["x"] < x1 + 900:
                return 1
        return None

    start = iv_index(start_x)
    if start is None:
        return False
    seen = {("I", start)}
    queue = [("I", start)]
    while queue:
        if tick:
            tick()
        node = queue.pop(0)
        edges = set()
        if node[0] == "I":
            lo, hi = ivs[node[1]]
            if lo <= goal_x <= hi or lo > goal_x:
                return True
            g, js = biome_phys(world.biome_at(hi))
            xs = {hi, hi - 15, hi - 30, hi - 50, hi - 80, hi - 120, hi - 170, lo + 5, (lo + hi) / 2}
            xs = [x for x in xs if lo <= x <= hi]
            nm = near_moving(lo, hi)
            ts = [0] if nm is None else (range(0, 320, 20) if nm == 0 else range(0, 210, 30))
            for x in xs:
                for t0 in ts:
                    try_jumps(x, GROUND_Y, t0, g, js, None, edges)
            p = world.pad_at(hi + 3)
            if p is not None:
                r = bounce(p["x"] - PAD_W / 2 + 1, 0, 1)
                if r is not None:
                    edges.add(r)
        elif node[0] == "P":
            d = plats[node[1]]
            g, js = biome_phys(world.biome_at(d["cx"]))
            for t0 in range(0, d["period"], 12):
                try_jumps(plat_x(d, t0), GROUND_Y, t0, g, js, None, edges)
        else:
            v = vines[node[1]]
            g, js = biome_phys(world.biome_at(v["x"]))
            for t0 in range(0, 210, 15):
                try_jumps(vine_bx(v, t0), VINE_BOTTOM + HANG_DROP, t0, g, js, v, edges)
        for e in edges:
            if e not in seen:
                seen.add(e)
                queue.append(e)
    return False


REQ_WINDOW = [10, 9, 8, 7, 6]   # charge frames of slack required per level
MIX_LIMITS = dict(tumble=(2, 6), geyser=(2, 5), updraft=(1, 4), icicle=(2, 6), croc=(2, 5), vine=(2, 5),
                  pad=(2, 6), wind=(2, 6), platform=(1, 4))


def mix_ok(w, cfg):
    """Every mechanic the level is meant to feature shows up, but not too often."""
    counts = {}
    for d in w.ents:
        counts[d["t"]] = counts.get(d["t"], 0) + 1
    for key, (lo, hi) in MIX_LIMITS.items():
        if cfg.get(key, 0) > 0 and not lo <= counts.get(key, 0) <= hi:
            return False
    if cfg["ice"] and len(w.ice) < 2:
        return False
    for t, key in (("vine", "vine_req"), ("pad", "pad_req")):
        if cfg.get(key, 0) > 0:
            items = [d for d in w.ents if d["t"] == t]
            n_req = sum(1 for d in items if d.get("req"))
            if not 1 <= n_req <= 3 or (items and items[0].get("req")):
                return False
    if cfg["obstacle"] and cfg["kinds"] and len(w.obstacles) < 2:
        return False
    return True


def build_all_levels(verbose=True, progress=None):
    levels = []
    for bi, b in enumerate(BIOMES):
        for lvl in range(1, 6):
            for attempt in range(200):
                seed = 1000 * (bi + 1) + 37 * lvl + attempt * 7919
                w, fx = build_level(bi, lvl, seed)
                tick = (lambda: progress(len(levels), len(BIOMES) * 5)) if progress else None
                if mix_ok(w, level_cfg(bi, lvl)) and solve(w, START_X, fx, REQ_WINDOW[lvl - 1], tick):
                    break
            else:
                raise RuntimeError("could not build %s %d" % (b["key"], lvl))
            data = w.to_data()
            data.update(biome=b["key"], level=lvl, finish=fx, seed=seed)
            levels.append(data)
            if progress:
                progress(len(levels), len(BIOMES) * 5)
            if verbose:
                print("  %-10s level %d  seed %-7d tries %d" % (b["name"], lvl, seed, attempt + 1))
    return levels


def save_levels(levels):
    with open(LEVELS_PATH, "w") as f:
        json.dump(dict(version=LEVELS_VERSION, levels=levels), f, separators=(",", ":"))


def load_levels(progress=None):
    try:
        with open(LEVELS_PATH) as f:
            data = json.load(f)
        if (isinstance(data, dict) and data.get("version") == LEVELS_VERSION
                and len(data.get("levels", [])) == len(BIOMES) * 5):
            return data["levels"]
        print("Level file is out of date - rebuilding and verifying levels (about 20 seconds)...")
    except (OSError, ValueError):
        print("Level file missing - building and verifying levels (about 20 seconds)...")
    levels = build_all_levels(verbose=False, progress=progress)
    try:
        save_levels(levels)
    except OSError:
        pass
    return levels


# ================================================================ save data
def load_save():
    """Progress = levels you actually beat (best_times). Cheats are a separate flag,
    so the reset code can remove them without touching real progress."""
    data = dict(cheat_unlock=False, blueberry=False, focus=3, best_times={}, best_classic=0, best_checkpoint=0)
    try:
        with open(SAVE_PATH) as f:
            loaded = json.load(f)
        data.update(loaded)
        if "unlocked" in loaded and "cheat_unlock" not in loaded:
            # older save: an "unlocked" count beyond what was really beaten came from the cheat code
            done = [int(k) for k in data["best_times"]]
            natural = max(done) + 1 if done else 0
            data["cheat_unlock"] = loaded["unlocked"] > natural
        data.pop("unlocked", None)
    except (OSError, ValueError):
        pass
    return data


def write_save(data):
    try:
        with open(SAVE_PATH, "w") as f:
            json.dump(data, f, indent=1)
    except OSError:
        pass


# ================================================================ everything below needs pygame
if __name__ == "__main__" and "--build-levels" in sys.argv:
    print("Building and verifying all levels...")
    save_levels(build_all_levels())
    print("Saved", LEVELS_PATH)
    sys.exit(0)

import pygame  # noqa: E402


# ---------------------------------------------------------------- effects
class Particle:
    def __init__(self, x, y, vx, vy, life, color, size, grav=0.3, shape="circle"):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.life = self.max_life = life
        self.color, self.size, self.grav, self.shape = color, size, grav, shape

    def update(self):
        self.vx *= 0.98
        self.vy += self.grav
        self.x += self.vx
        self.y += self.vy
        self.life -= 1

    def draw(self, surf, cam_x, off):
        k = self.life / self.max_life
        r = max(1, self.size * (0.4 + 0.6 * k))
        sx, sy = self.x - cam_x + off[0], self.y + off[1]
        if sx < -50 or sx > W + 50:
            return
        if self.shape == "star":
            pts = []
            for i in range(8):
                a = i * math.pi / 4 + self.life * 0.2
                rr = r * (1.0 if i % 2 == 0 else 0.4)
                pts.append((sx + math.cos(a) * rr, sy + math.sin(a) * rr))
            pygame.draw.polygon(surf, self.color, pts)
        elif self.shape == "ring":
            pygame.draw.circle(surf, self.color, (int(sx), int(sy)), int(r), 1)
        elif self.shape == "streak":
            pygame.draw.line(surf, self.color, (sx, sy), (sx - self.vx * 4, sy - self.vy * 4), 2)
        else:
            pygame.draw.circle(surf, self.color, (int(sx), int(sy)), int(r))


class FloatText:
    def __init__(self, text, x, y, color):
        self.text, self.x, self.y, self.color = text, x, y, color
        self.life = 70


# ---------------------------------------------------------------- player
class Player:
    def __init__(self, x):
        self.x = float(x)
        self.y = float(GROUND_Y)
        self.vx = self.vy = 0.0
        self.g = 0.5
        self.state = "ground"   # ground, air, hang, fall, sink, crash, ko, gone
        self.charging = False
        self.charge_frames = 0
        self.charge_max = CHARGE_FRAMES
        self.facing = 1
        self.walk_phase = 0.0
        self.walking = False
        self.angle = 0.0
        self.flipping = False
        self.spin_rate = 0.0
        self.land_squash = 1.0
        self.jump_charge = 0.0
        self.slide = False
        self.slide_t = 0
        self.slide_x0 = self.slide_x1 = 0.0
        self.plat = None
        self.vine = None
        self.exclude = None
        self.grab_buffer = 0
        self.dead_seg = None
        self.liquid = None

    @property
    def charge(self):
        return min(1.0, self.charge_frames / self.charge_max)


def build_player_sprite(pose, phase, facing, dead=False):
    """Draw the little runner onto a 70x90 surface. Feet sit at y=88."""
    s = pygame.Surface((70, 90), pygame.SRCALPHA)
    f = facing
    cx = 35
    hip = (cx, 60)
    shoulder = (cx, 42)
    pants, pants_back = (55, 70, 140), (40, 50, 105)
    shirt = (235, 92, 62)
    skin, skin_back = (255, 212, 172), (225, 180, 145)
    shoe = (40, 35, 40)

    if pose == "walk":
        a = math.sin(phase) * 0.65
        legs = []
        for ang in (a, -a):
            knee = (hip[0] + math.sin(ang) * 13 * f, hip[1] + 12)
            foot = (hip[0] + math.sin(ang) * 22 * f, 86 - max(0, -math.cos(phase)) * 2)
            legs.append((knee, foot))
        arms = []
        for ang in (-a, a):
            arms.append(((shoulder[0] + math.sin(ang) * 8 * f, shoulder[1] + 10),
                         (shoulder[0] + math.sin(ang) * 15 * f, shoulder[1] + 18)))
    elif pose == "crouch":
        legs = [((cx + 11 * f, 70), (cx + 6 * f, 86)), ((cx - 2 * f, 72), (cx - 6 * f, 86))]
        arms = [((cx - 10 * f, 48), (cx - 18 * f, 54)), ((cx - 7 * f, 50), (cx - 15 * f, 57))]
    elif pose == "air":
        legs = [((cx + 12 * f, 66), (cx + 4 * f, 78)), ((cx + 6 * f, 70), (cx - 4 * f, 80))]
        arms = [((cx + 10 * f, 32), (cx + 14 * f, 20)), ((cx - 8 * f, 32), (cx - 12 * f, 20))]
    elif pose == "hang":
        sw = math.sin(phase) * 4
        legs = [((cx + 3 + sw, 74), (cx + 5 + sw * 1.5, 87)), ((cx - 3 + sw, 74), (cx - 2 + sw * 1.5, 87))]
        arms = [((cx + 7, 28), (cx + 3, 6)), ((cx - 7, 28), (cx - 3, 6))]
    elif pose == "flail":
        w = math.sin(phase * 2) * 8
        legs = [((cx + 8, 72 + w * 0.3), (cx + 14, 84)), ((cx - 8, 72 - w * 0.3), (cx - 14, 84))]
        arms = [((cx + 12, 34 + w), (cx + 20, 24 + w)), ((cx - 12, 34 - w), (cx - 20, 24 - w))]
    else:
        legs = [((cx + 4 * f, 73), (cx + 5 * f, 86)), ((cx - 4 * f, 73), (cx - 5 * f, 86))]
        arms = [((cx + 6 * f, 51), (cx + 8 * f, 59)), ((cx - 6 * f, 51), (cx - 8 * f, 59))]

    def limb(start, mid, end, color, width):
        pygame.draw.line(s, color, start, mid, width)
        pygame.draw.line(s, color, mid, end, width)
        pygame.draw.circle(s, color, (int(mid[0]), int(mid[1])), width // 2)

    limb(hip, legs[1][0], legs[1][1], pants_back, 7)
    pygame.draw.ellipse(s, shoe, (legs[1][1][0] - 5 + 2 * f, legs[1][1][1] - 3, 10, 6))
    limb(shoulder, arms[1][0], arms[1][1], skin_back, 5)
    pygame.draw.rect(s, shirt, (cx - 11, 34, 22, 30), border_radius=8)
    pygame.draw.rect(s, (200, 70, 50), (cx - 11, 56, 22, 6), border_radius=3)
    limb(hip, legs[0][0], legs[0][1], pants, 7)
    pygame.draw.ellipse(s, shoe, (legs[0][1][0] - 5 + 2 * f, legs[0][1][1] - 3, 10, 6))
    limb(shoulder, arms[0][0], arms[0][1], skin, 5)

    head = (cx, 22)
    pygame.draw.circle(s, skin, head, 13)
    pygame.draw.circle(s, (40, 110, 210), head, 13, draw_top_left=True, draw_top_right=True)
    pygame.draw.rect(s, (40, 110, 210), (cx - 13, 20, 26, 3))
    visor_x = cx + 6 if f > 0 else cx - 20
    pygame.draw.rect(s, (30, 85, 170), (visor_x, 20, 14, 4), border_radius=2)
    ex = cx + 5 * f
    if dead:
        pygame.draw.line(s, BLACK, (ex - 3, 22), (ex + 3, 28), 2)
        pygame.draw.line(s, BLACK, (ex + 3, 22), (ex - 3, 28), 2)
    else:
        pygame.draw.circle(s, WHITE, (ex, 26), 4)
        pygame.draw.circle(s, BLACK, (ex + f, 26), 2)
        pygame.draw.line(s, (150, 80, 70), (cx + 2 * f, 32), (cx + 8 * f, 31), 2)
    return s


# ---------------------------------------------------------------- runtime entities
def player_rect(p):
    return (p.x - PHW, p.y - PH, PHW * 2, PH)


class RT:
    front = False

    def __init__(self, d):
        self.d = d

    def right(self):
        return ent_right(self.d)

    def update(self, g):
        pass

    def hit(self, g):
        return None

    def draw(self, g, off):
        pass

    def reset(self):
        pass


class Tumble:
    def __init__(self, x, r, speed):
        self.x, self.r, self.speed = x, r, speed
        self.y = GROUND_Y - r
        self.phase = 0.0
        self.falling = False
        self.vy = 0.0
        self.alive = True

    def update(self, g):
        if not self.falling:
            self.x -= self.speed
            self.phase += self.speed * 0.05
            self.y = GROUND_Y - self.r - abs(math.sin(self.phase * 1.3)) * 12
            seg = g.world.segment_at(self.x)
            if seg is None or seg.kind != "ground":
                self.falling = True
        else:
            self.vy += 0.5
            self.y += self.vy
            self.x -= self.speed * 0.5
            if self.y > H + 60:
                self.alive = False

    def hits(self, p):
        cx = clamp(self.x, p.x - PHW, p.x + PHW)
        cy = clamp(self.y, p.y - PH, p.y)
        rr = self.r * 0.78
        return (self.x - cx) ** 2 + (self.y - cy) ** 2 < rr * rr

    def draw(self, g, off):
        sx, sy = self.x - g.cam_x + off[0], self.y + off[1]
        if sx < -40 or sx > W + 40:
            return
        if not self.falling:
            sh = pygame.Surface((int(self.r * 2), 6), pygame.SRCALPHA)
            pygame.draw.ellipse(sh, (0, 0, 0, 50), sh.get_rect())
            g.screen.blit(sh, (sx - self.r, GROUND_Y + off[1] - 3))
        rot = -self.x / self.r
        col, col2 = (150, 110, 60), (196, 156, 96)
        pygame.draw.circle(g.screen, col2, (int(sx), int(sy)), int(self.r), 2)
        for i in range(7):
            a = rot + i * 0.9
            a2 = a + 2.2
            p1 = (sx + math.cos(a) * self.r * 0.95, sy + math.sin(a) * self.r * 0.95)
            p2 = (sx + math.cos(a2) * self.r * 0.6, sy + math.sin(a2) * self.r * 0.6)
            pygame.draw.line(g.screen, col if i % 2 else col2, p1, p2, 2)


class Emitter(RT):
    def __init__(self, d):
        super().__init__(d)
        self.reset()

    def reset(self):
        self.timer = 30
        self.pair_timer = -1
        self.count = 0

    def spawn(self, g):
        self.count += 1
        r = 14 + (self.count * 5) % 6
        g.weeds.append(Tumble(self.d["x"], r, self.d["speed"]))

    def update(self, g):
        p = g.player
        if g.dead or not (self.d["x0"] - 650 < p.x < self.d["x"] - 150):
            return
        self.timer -= 1
        if self.timer <= 0:
            self.spawn(g)
            self.timer = self.d["interval"]
            if self.d["pair"]:
                self.pair_timer = 40
        if self.pair_timer > 0:
            self.pair_timer -= 1
            if self.pair_timer == 0:
                self.spawn(g)


class Icicle(RT):
    front = True

    def __init__(self, d):
        super().__init__(d)
        self.reset()

    def reset(self):
        if getattr(self, "state", None) == "gone":
            return  # already broken
        self.state, self.y, self.vy, self.timer = "hang", 95.0, 0.0, 0

    def update(self, g):
        x = self.d["x"]
        p = g.player
        if self.state == "hang":
            if abs(p.x - x) < 150 and p.x < x + 60 and not g.dead:
                self.state, self.timer = "shake", 40
        elif self.state == "shake":
            self.timer -= 1
            if self.timer <= 0:
                self.state = "fall"
        elif self.state == "fall":
            self.vy += 0.6
            self.y += self.vy
            if self.y >= GROUND_Y:
                self.state = "gone"
                for _ in range(14):
                    g.particles.append(Particle(x, GROUND_Y - 4, random.uniform(-3, 3), random.uniform(-5, -1),
                                                30, random.choice([(200, 235, 255), WHITE]), random.uniform(2, 5), 0.3))

    def hit(self, g):
        if self.state == "gone":
            return None
        x = self.d["x"]
        if rect_hit(*player_rect(g.player), x - 7, self.y - 55, 14, 55):
            return ("crash", "An icicle fell on you!")
        return None

    def draw(self, g, off):
        x = self.d["x"] - g.cam_x + off[0]
        if x < -100 or x > W + 100:
            return
        rock = [(x - 75, -5), (x + 75, -5), (x + 62, 30), (x + 30, 44), (x - 20, 42), (x - 60, 28)]
        pygame.draw.polygon(g.screen, (96, 100, 116), rock)
        pygame.draw.polygon(g.screen, (240, 246, 255), [(x - 75, -5), (x + 75, -5), (x + 66, 10), (x - 66, 10)])
        if self.state == "gone":
            pygame.draw.polygon(g.screen, (200, 230, 250), [(x - 6, 40), (x + 6, 40), (x, 50)])
            return
        jx = random.uniform(-2, 2) if self.state == "shake" else 0
        y = self.y + off[1]
        tri = [(x - 8 + jx, y - 55), (x + 8 + jx, y - 55), (x + jx, y)]
        pygame.draw.polygon(g.screen, (190, 228, 255), tri)
        pygame.draw.polygon(g.screen, (120, 170, 220), tri, 2)
        pygame.draw.line(g.screen, WHITE, (x - 3 + jx, y - 50), (x - 1 + jx, y - 15), 2)


class Croc(RT):
    front = True

    def __init__(self, d):
        super().__init__(d)
        self.reset()

    def reset(self):
        self.state, self.rise, self.timer = "idle", 0.0, 0

    def update(self, g):
        p = g.player
        x = self.d["x"]
        if self.state == "idle":
            if p.state == "air" and abs(p.x - x) < 110 and p.y > GROUND_Y - 120:
                self.state, self.timer = "snap", 0
        else:
            self.timer += 1
            t = self.timer
            self.rise = min(1.0, t / 8) if t < 28 else max(0.0, 1 - (t - 28) / 20)
            if t > 48:
                self.state, self.rise = "idle", 0.0

    def hit(self, g):
        if self.rise < 0.3:
            return None
        hgt = 95 * self.rise
        if rect_hit(*player_rect(g.player), self.d["x"] - 30, GROUND_Y + 20 - hgt, 60, hgt):
            return ("croc", "Chomp! A crocodile got you.")
        return None

    def draw(self, g, off):
        x = self.d["x"] - g.cam_x + off[0]
        if x < -100 or x > W + 100:
            return
        sy = GROUND_Y + 20 + off[1]
        green, dark = (70, 130, 60), (40, 90, 40)
        if self.rise <= 0.02:
            bob = math.sin(g.t * 0.06 + self.d["x"]) * 2
            for dx in (-14, 0, 14):
                pygame.draw.ellipse(g.screen, dark, (x + dx - 8, sy - 6 + bob, 16, 10))
            for dx in (-8, 8):
                pygame.draw.circle(g.screen, green, (int(x + dx - 26), int(sy - 3 + bob)), 6)
                pygame.draw.circle(g.screen, (255, 230, 80), (int(x + dx - 26), int(sy - 4 + bob)), 3)
                pygame.draw.circle(g.screen, BLACK, (int(x + dx - 26), int(sy - 4 + bob)), 1)
            return
        top = sy - 95 * self.rise
        gape = 0.6 if self.timer < 22 else max(0.0, 0.6 - (self.timer - 22) * 0.12)
        lower = [(x - 26, sy), (x + 26, sy), (x + 12, top + 20), (x - 12, top + 20)]
        pygame.draw.polygon(g.screen, green, lower)
        upper_tip = (x - 34 * gape, top)
        jaw1 = [(x - 14, top + 30), (x + 16, top + 26), upper_tip]
        jaw2 = [(x - 10, top + 30), (x + 14, top + 30), (x + 34 * gape, top + 2)]
        pygame.draw.polygon(g.screen, green, jaw1)
        pygame.draw.polygon(g.screen, green, jaw2)
        for i in range(4):
            tx = x - 10 + i * 6
            pygame.draw.polygon(g.screen, WHITE, [(tx, top + 28), (tx + 3, top + 20), (tx + 6, top + 28)])
        pygame.draw.circle(g.screen, (255, 230, 80), (int(x + 4), int(top + 36)), 4)
        pygame.draw.circle(g.screen, BLACK, (int(x + 4), int(top + 36)), 2)


class Pad(RT):
    def __init__(self, d):
        super().__init__(d)
        self.squish = 0.0

    def update(self, g):
        self.squish *= 0.85

    def draw(self, g, off):
        x = self.d["x"] - g.cam_x + off[0]
        if x < -60 or x > W + 60:
            return
        gy = GROUND_Y + off[1]
        sq = self.squish
        b = g.world.biome_at(self.d["x"])
        if b == "sky":
            yy = gy - 14 + sq * 8
            for dx, r in ((-16, 12), (0, 16), (16, 12)):
                pygame.draw.circle(g.screen, (236, 244, 255), (int(x + dx), int(yy)), int(r))
            pygame.draw.circle(g.screen, WHITE, (int(x - 3), int(yy - 4)), 9)
        else:
            pygame.draw.rect(g.screen, (90, 90, 104), (x - PAD_W / 2, gy - 8, PAD_W, 8), border_radius=3)
            hgt = 14 - sq * 9
            for i in range(3):
                yy = gy - 8 - (i + 1) * hgt / 3
                pygame.draw.line(g.screen, (200, 200, 210), (x - 14, yy + hgt / 6), (x + 14, yy), 3)
            pygame.draw.rect(g.screen, (230, 70, 60), (x - PAD_W / 2 + 4, gy - 12 - hgt, PAD_W - 8, 6),
                             border_radius=3)


class Geyser(RT):
    front = True
    PERIOD = 200

    def phase(self, g):
        return (g.world_t + self.d["phase"]) % self.PERIOD

    def column(self, g):
        ph = self.phase(g)
        if ph < 150:
            return 0.0
        k = min(1.0, (ph - 150) / 8, (self.PERIOD - ph) / 8)
        return 170 * k

    def update(self, g):
        ph = self.phase(g)
        x = self.d["x"]
        if 110 <= ph < 150 and g.t % 5 == 0 and abs(x - g.player.x) < W:
            g.particles.append(Particle(x + random.uniform(-10, 10), GROUND_Y - 4, random.uniform(-0.4, 0.4),
                                        random.uniform(-2, -1), 40, (120, 110, 110), random.uniform(4, 8), -0.01))

    def hit(self, g):
        hgt = self.column(g)
        if hgt <= 0:
            return None
        if rect_hit(*player_rect(g.player), self.d["x"] - 16, GROUND_Y - hgt, 32, hgt):
            return ("burn", "Fwoosh! A fire geyser erupted under you.")
        return None

    def draw(self, g, off):
        x = self.d["x"] - g.cam_x + off[0]
        if x < -60 or x > W + 60:
            return
        gy = GROUND_Y + off[1]
        ph = self.phase(g)
        glow = (255, 120, 40) if ph >= 110 else (120, 50, 30)
        pygame.draw.ellipse(g.screen, (30, 20, 20), (x - 20, gy - 4, 40, 10))
        pygame.draw.ellipse(g.screen, glow, (x - 12, gy - 2, 24, 5))
        hgt = self.column(g)
        if hgt > 0:
            for layer, (col, wd) in enumerate((((255, 90, 30), 18), ((255, 170, 50), 12), ((255, 240, 150), 6))):
                pts = [(x - wd, gy)]
                n = 6
                for i in range(1, n + 1):
                    yy = gy - hgt * i / n
                    pts.append((x - wd * (1 - i / (n + 2)) + math.sin(g.t * 0.5 + i + layer) * 3, yy))
                pts.append((x + math.sin(g.t * 0.3) * 4, gy - hgt - 10))
                for i in range(n, 0, -1):
                    yy = gy - hgt * i / n
                    pts.append((x + wd * (1 - i / (n + 2)) + math.cos(g.t * 0.5 + i + layer) * 3, yy))
                pts.append((x + wd, gy))
                pygame.draw.polygon(g.screen, col, pts)


class Checkpoint(RT):
    def __init__(self, d):
        super().__init__(d)
        self.active = False
        self.raise_t = 0.0

    def update(self, g):
        if self.active:
            self.raise_t = min(1.0, self.raise_t + 0.05)
        elif g.player.state == "ground" and g.player.x >= self.d["x"] and not g.dead:
            self.active = True
            g.checkpoint_x = self.d["x"]
            g.texts.append(FloatText("Checkpoint!", self.d["x"], GROUND_Y - 110, (120, 255, 140)))
            for _ in range(16):
                g.particles.append(Particle(self.d["x"], GROUND_Y - 60, random.uniform(-3, 3), random.uniform(-4, 0),
                                            35, random.choice([(120, 255, 140), WHITE]), 4, 0.15, "star"))

    def draw(self, g, off):
        x = self.d["x"] - g.cam_x + off[0]
        if x < -60 or x > W + 60:
            return
        gy = GROUND_Y + off[1]
        pygame.draw.rect(g.screen, (90, 90, 100), (x - 2, gy - 90, 4, 90))
        fy = gy - 40 - 46 * self.raise_t
        col = (80, 220, 110) if self.active else (220, 220, 220)
        wave = math.sin(g.t * 0.15) * 3
        pygame.draw.polygon(g.screen, col, [(x + 2, fy), (x + 32, fy + 8 + wave), (x + 2, fy + 18)])


class Static(RT):
    def __init__(self, d):
        super().__init__(d)

    def update(self, g):
        t = self.d["t"]
        if t == "wind" and g.t % 3 == 0:
            d = self.d
            if d["x1"] > g.cam_x and d["x0"] < g.cam_x + W:
                x = random.uniform(d["x0"], d["x1"])
                y = random.uniform(GROUND_Y - 260, GROUND_Y - 10)
                g.particles.append(Particle(x, y, d["dir"] * random.uniform(4, 7), 0, 26,
                                            (255, 255, 255), 2, 0, "streak"))
        elif t == "updraft" and g.t % 4 == 0:
            d = self.d
            if d["x1"] > g.cam_x and d["x0"] < g.cam_x + W:
                x = random.uniform(d["x0"], d["x1"])
                g.particles.append(Particle(x, GROUND_Y + 10, random.uniform(-0.3, 0.3), random.uniform(-3, -2),
                                            70, random.choice([(255, 170, 60), (255, 220, 120)]), 2.5, -0.01))

    def draw(self, g, off):
        d = self.d
        t = d["t"]
        scr = g.screen
        gy = GROUND_Y + off[1]
        if t == "vine":
            bx = vine_bx(d, g.world_t) - g.cam_x + off[0]
            if bx < -60 or bx > W + 60:
                return
            topx = d["x"] - g.cam_x + off[0]
            pts = []
            n = 10
            for i in range(n + 1):
                k = i / n
                pts.append((topx + (bx - topx) * k * k, -10 + (VINE_BOTTOM + off[1] + 10) * k))
            pygame.draw.lines(scr, (52, 120, 46), False, pts, 5)
            for i in range(1, n, 2):
                px, py = pts[i]
                side = 1 if i % 4 == 1 else -1
                pygame.draw.ellipse(scr, (80, 170, 70), (px + (2 if side > 0 else -14), py - 4, 12, 7))
            pygame.draw.circle(scr, (52, 120, 46), (int(bx), int(VINE_BOTTOM + off[1])), 6, 3)
        elif t == "wind":
            x = d["x0"] + 4 - g.cam_x + off[0]
            if x < -80 or x > W + 80:
                return
            pygame.draw.rect(scr, (110, 90, 70), (x - 2, gy - 70, 4, 70))
            dr = d["dir"]
            flap = math.sin(g.t * 0.4) * 3
            sock = [(x, gy - 70), (x + dr * 40, gy - 64 + flap), (x + dr * 40, gy - 58 + flap), (x, gy - 52)]
            pygame.draw.polygon(scr, (240, 90, 60), sock)
            pygame.draw.line(scr, WHITE, (x + dr * 14, gy - 68), (x + dr * 14, gy - 54), 3)
            pygame.draw.line(scr, WHITE, (x + dr * 28, gy - 66 + flap), (x + dr * 28, gy - 57 + flap), 3)
        elif t == "updraft":
            x0, x1 = d["x0"] - g.cam_x + off[0], d["x1"] - g.cam_x + off[0]
            if x1 < 0 or x0 > W:
                return
            surf = pygame.Surface((max(1, int(x1 - x0)), 300), pygame.SRCALPHA)
            for i in range(0, int(x1 - x0), 18):
                yy = (g.t * 3 + i * 37) % 300
                pygame.draw.line(surf, (255, 200, 120, 60), (i, 300 - yy), (i + 4, 260 - yy), 3)
            scr.blit(surf, (x0, gy - 300 + 20))
        elif t == "platform":
            x = plat_x(d, g.world_t) - g.cam_x + off[0]
            if x < -100 or x > W + 100:
                return
            wd = d["w"]
            pygame.draw.polygon(scr, (150, 120, 90), [(x - wd / 2, gy + 6), (x + wd / 2, gy + 6), (x, gy + 40)])
            pygame.draw.rect(scr, (110, 190, 100), (x - wd / 2, gy - 2, wd, 10), border_radius=4)
            for i in range(3):
                pygame.draw.circle(scr, (236, 244, 255), (int(x - 30 + i * 30), int(gy + 18)), 9)
        elif t == "sign":
            x = d["x"] - g.cam_x + off[0]
            if x < -150 or x > W + 150:
                return
            name = BIOME_BY_KEY[d["biome"]]["name"]
            txt = g.font_small.render(name, True, WHITE)
            bw = txt.get_width() + 24
            pygame.draw.rect(scr, (110, 80, 50), (x - 3, gy - 60, 6, 60))
            board = pygame.Rect(0, 0, bw, 34)
            board.midbottom = (int(x), int(gy - 50))
            pygame.draw.rect(scr, (150, 105, 62), board, border_radius=6)
            pygame.draw.rect(scr, (100, 70, 40), board, 3, border_radius=6)
            scr.blit(txt, txt.get_rect(center=board.center))
        elif t == "finish":
            x = d["x"] - g.cam_x + off[0]
            if x < -80 or x > W + 80:
                return
            pygame.draw.rect(scr, (80, 80, 90), (x - 3, gy - 130, 6, 130))
            wave = math.sin(g.t * 0.12) * 4
            for r in range(4):
                for c in range(6):
                    col = BLACK if (r + c) % 2 == 0 else WHITE
                    cx = x + 3 + c * 9
                    cy = gy - 128 + r * 9 + math.sin(g.t * 0.12 + c * 0.6) * 3
                    pygame.draw.rect(scr, col, (cx, cy + wave * 0.3, 9, 9))
            lab = g.font_small.render("FINISH", True, WHITE)
            scr.blit(lab, lab.get_rect(midbottom=(x, gy - 136)))


def make_rt(d):
    t = d["t"]
    if t == "tumble":
        return Emitter(d)
    if t == "icicle":
        return Icicle(d)
    if t == "croc":
        return Croc(d)
    if t == "pad":
        return Pad(d)
    if t == "geyser":
        return Geyser(d)
    if t == "checkpoint":
        return Checkpoint(d)
    return Static(d)


# ---------------------------------------------------------------- UI
class Button:
    def __init__(self, rect, text, action, sub="", enabled=True, preview=None, done=False, color=None):
        self.rect = pygame.Rect(rect)
        self.text, self.action, self.sub = text, action, sub
        self.enabled, self.preview, self.done = enabled, preview, done
        self.color = color or (235, 75, 55)

    def draw(self, g, selected):
        scr = g.screen
        r = self.rect
        hover = r.collidepoint(pygame.mouse.get_pos())
        lift = -3 if (hover or selected) and self.enabled else 0
        rr = r.move(0, lift)
        if self.preview:
            pygame.draw.rect(scr, (20, 20, 30), r.move(0, 5), border_radius=14)
            prev = pygame.transform.smoothscale(g.sky_cache[self.preview], (rr.w, rr.h))
            scr.blit(prev, rr.topleft)
            b = BIOME_BY_KEY[self.preview]
            ground = pygame.Rect(rr.x, rr.bottom - rr.h // 3, rr.w, rr.h // 3)
            pygame.draw.rect(scr, b["dirt"], ground)
            pygame.draw.rect(scr, b["top"], (rr.x, ground.y, rr.w, 8))
            if not self.enabled:
                sh = pygame.Surface(rr.size, pygame.SRCALPHA)
                sh.fill((20, 20, 30, 170))
                scr.blit(sh, rr.topleft)
            pygame.draw.rect(scr, WHITE if (hover or selected) and self.enabled else (40, 40, 60), rr, 4,
                             border_radius=14)
            lab = g.font_med.render(self.text, True, WHITE)
            sh_lab = g.font_med.render(self.text, True, (20, 20, 30))
            scr.blit(sh_lab, sh_lab.get_rect(center=(rr.centerx + 2, rr.y + 32)))
            scr.blit(lab, lab.get_rect(center=(rr.centerx, rr.y + 30)))
            if self.sub:
                s = g.font_small.render(self.sub, True, WHITE)
                scr.blit(s, s.get_rect(center=(rr.centerx, rr.bottom - 20)))
            if self.done:
                self.draw_check(scr, rr)
            return
        base = self.color if self.enabled else (120, 120, 130)
        dark = tuple(int(c * 0.65) for c in base)
        pygame.draw.rect(scr, dark, r.move(0, 6), border_radius=14)
        col = lerp_color(base, WHITE, 0.15) if (hover or selected) and self.enabled else base
        pygame.draw.rect(scr, col, rr, border_radius=14)
        pygame.draw.rect(scr, WHITE if selected and self.enabled else dark, rr, 3, border_radius=14)
        lab = g.font_med.render(self.text, True, WHITE)
        if self.sub:
            scr.blit(lab, lab.get_rect(center=(rr.centerx, rr.centery - 11)))
            s = g.font_small.render(self.sub, True, (255, 240, 230))
            scr.blit(s, s.get_rect(center=(rr.centerx, rr.centery + 16)))
        else:
            scr.blit(lab, lab.get_rect(center=rr.center))
        if self.done:
            self.draw_check(scr, rr)

    @staticmethod
    def draw_check(scr, rr):
        pygame.draw.circle(scr, (40, 150, 70), (rr.right - 14, rr.top + 14), 13)
        pygame.draw.circle(scr, WHITE, (rr.right - 14, rr.top + 14), 13, 2)
        pygame.draw.lines(scr, WHITE, False, [(rr.right - 20, rr.top + 14), (rr.right - 15, rr.top + 19),
                                               (rr.right - 7, rr.top + 9)], 3)


def fmt_time(sec):
    return "%d:%04.1f" % (int(sec) // 60, sec % 60)


# ---------------------------------------------------------------- game
class Game:
    def __init__(self, screen):
        self.screen = screen
        self.clock = pygame.time.Clock()
        self.font_big = pygame.font.Font(None, 84)
        self.font_med = pygame.font.Font(None, 42)
        self.font_small = pygame.font.Font(None, 28)
        self.button_rect = pygame.Rect(W - 175, H - 105, 150, 80)
        self.focus_rect = pygame.Rect(20, 84, 250, 46)
        self.focus_edit = False
        self.focus_err = 0
        self.vignette = self._make_vignette()
        self.sky_cache = {b["key"]: self._make_sky(b) for b in BIOMES}
        self.clouds = [[random.uniform(0, W + 400), random.uniform(30, 200),
                        random.uniform(0.6, 1.4), random.uniform(0.1, 0.35)] for _ in range(7)]
        self.stars = [(random.uniform(0, W), random.uniform(0, H * 0.7), random.uniform(0, 6.28),
                       random.choice([1, 1, 2])) for _ in range(110)]
        self.levels = load_levels(self.show_loading)
        self.save = load_save()
        self.t = 0
        self.cam_x = 0.0
        self.ambient = []
        self.ambient_kind = None
        self.bg_biome = "meadow"
        self.fade = 0.0
        self.buttons, self.sel, self.back = [], 0, None
        self.world = None
        self.ctx = None
        self.paused = False
        self.goto_title()

    # ================================================== setup helpers
    def show_loading(self, done, total):
        """Keep the window alive and show progress while levels are being built."""
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
        scr = self.screen
        scr.blit(self.sky_cache["meadow"], (0, 0))
        self.shadow_text("LEAP RUNNER", self.font_big, (W // 2, 170), (255, 230, 90), anchor="center")
        self.shadow_text("Building levels (only after an update)...", self.font_med, (W // 2, 260), WHITE,
                         anchor="center")
        bw = 460
        bx = W // 2 - bw // 2
        pygame.draw.rect(scr, (30, 30, 45), (bx - 4, 300, bw + 8, 28), border_radius=14)
        pygame.draw.rect(scr, (80, 210, 110), (bx, 304, max(8, int(bw * done / total)), 20), border_radius=10)
        self.shadow_text("%d / %d" % (done, total), self.font_small, (W // 2, 352), WHITE, anchor="center")
        pygame.display.flip()

    def _make_vignette(self):
        surf = pygame.Surface((W, H), pygame.SRCALPHA)
        for i in range(60):
            a = int(150 * (1 - i / 60) ** 2)
            pygame.draw.rect(surf, (120, 0, 20, a), (i * 4, i * 3, W - i * 8, H - i * 6), 4)
        return surf

    def _make_sky(self, b):
        surf = pygame.Surface((W, H))
        top, bot = b["sky"]
        for y in range(H):
            pygame.draw.line(surf, lerp_color(top, bot, y / H), (0, y), (W, y))
        return surf

    def set_menu(self, buttons, back=None, sel=0):
        self.buttons = buttons
        self.back = back
        enabled = [i for i, b in enumerate(buttons) if b.enabled]
        self.sel = sel if sel in enabled else (enabled[0] if enabled else 0)

    # ================================================== screens
    def goto_title(self):
        self.state = "title"
        self.world = None
        self.bg_biome = "meadow"
        cx = W // 2
        self.set_menu([
            Button((cx - 150, 250, 300, 70), "Levels", self.goto_biomes,
                   sub="%d / %d beaten" % (self.completed_count(), len(BIOMES) * 5)),
            Button((cx - 150, 335, 300, 70), "Sandbox", self.goto_sandbox, sub="endless & random",
                   color=(60, 140, 230)),
            Button((cx - 150, 420, 300, 60), "Quit", self.quit, color=(110, 110, 125)),
            Button((W - 170, H - 76, 150, 52), "Cheats", self.goto_cheats, color=(150, 90, 200)),
        ], back=self.quit)

    def goto_cheats(self):
        self.state = "cheats"
        self.cheat_text = ""
        self.cheat_msg = ""
        self.cheat_show = False
        cx = W // 2
        self.show_btn = Button((cx - 105, 350, 210, 60), "Show", self.toggle_cheat_show, color=(60, 140, 230))
        self.set_menu([
            Button((cx - 330, 350, 210, 60), "Enter", self.submit_cheat, color=(150, 90, 200)),
            self.show_btn,
            Button((cx + 120, 350, 210, 60), "Back", self.goto_title, color=(110, 110, 125)),
        ], back=self.goto_title)

    def toggle_cheat_show(self):
        """Reveal or hide what you've typed, so you can check for typos before pressing Enter."""
        self.cheat_show = not self.cheat_show
        self.show_btn.text = "Hide" if self.cheat_show else "Show"

    def active_cheats(self):
        names = []
        if self.save.get("cheat_unlock"):
            names.append("all levels unlocked")
        if self.save.get("blueberry"):
            names.append("blueberry (focus %d)" % self.save.get("focus", 3))
        return names

    def effective_charge(self):
        """Charge after focus wobble: the meter, the aim preview and the jump all use this value."""
        p = self.player
        amp = FOCUS_WOBBLE[self.focus_level()]
        if amp == 0 or not p.charging:
            return p.charge
        return clamp(p.charge + amp * math.sin(self.t * FOCUS_WOBBLE_SPEED), 0.0, 1.0)

    def focus_level(self):
        return int(self.save.get("focus", 3)) if self.save.get("blueberry") else 3

    def submit_cheat(self):
        if self.cheat_text == SECRET_CODE:
            self.save["cheat_unlock"] = True
            write_save(self.save)
            self.cheat_msg = "All levels unlocked!"
        elif self.cheat_text == FOCUS_CODE:
            self.save["blueberry"] = not self.save.get("blueberry")
            write_save(self.save)
            self.cheat_msg = ("Blueberry ON - click the Focus box in game" if self.save["blueberry"]
                              else "Blueberry OFF")
        elif self.cheat_text == RESET_CODE:
            self.save["cheat_unlock"] = False   # undo cheats, keep levels you really beat
            self.save["blueberry"] = False
            write_save(self.save)
            self.cheat_msg = "All cheats off - your progress is kept"
        elif self.cheat_text:
            self.cheat_msg = "Wrong code"
        self.cheat_text = ""

    def goto_biomes(self):
        self.state = "biomes"
        btns = []
        cw, ch = 205, 130
        for i, b in enumerate(BIOMES):
            row, col = divmod(i, 4)
            n_in_row = 4 if row == 0 else 3
            x0 = (W - (n_in_row * cw + (n_in_row - 1) * 20)) // 2
            rect = (x0 + col * (cw + 20), 130 + row * (ch + 30), cw, ch)
            unlocked = any(self.is_unlocked(i * 5 + l) for l in range(5))
            done = sum(1 for l in range(5) if self.is_done(i * 5 + l))
            if not unlocked:
                sub = "Locked"
            elif done == 5:
                sub = "Complete!"
            else:
                sub = "%d / 5 done" % done
            btns.append(Button(rect, b["name"], (lambda k=i: self.goto_levels(k)), sub=sub,
                               enabled=unlocked, preview=b["key"], done=done == 5))
        btns.append(Button((30, H - 80, 140, 56), "Back", self.goto_title, color=(110, 110, 125)))
        self.set_menu(btns, back=self.goto_title)

    def goto_levels(self, bi):
        self.state = "levels"
        self.menu_biome = bi
        self.bg_biome = BIOMES[bi]["key"]
        btns = []
        for l in range(5):
            idx = bi * 5 + l
            unlocked = self.is_unlocked(idx)
            done = self.is_done(idx)
            if done:          # stage 1: completed (green, check mark, best time)
                sub, color = "Best " + fmt_time(self.save["best_times"][str(idx)]), (60, 170, 90)
            elif unlocked:    # stage 2: open but not beaten yet
                sub, color = "%d m" % LEVEL_LENGTHS_M[l], None
            else:             # stage 3: locked (grey, can't click)
                sub, color = "Locked", None
            rect = (W // 2 - 380 + l * 154, 230, 140, 110)
            btns.append(Button(rect, "Level %d" % (l + 1), (lambda i=idx: self.start_level(i)), sub=sub,
                               enabled=unlocked, done=done, color=color))
        btns.append(Button((30, H - 80, 140, 56), "Back", self.goto_biomes, color=(110, 110, 125)))
        todo = [l for l in range(5) if self.is_unlocked(bi * 5 + l) and not self.is_done(bi * 5 + l)]
        self.set_menu(btns, back=self.goto_biomes, sel=todo[0] if todo else 0)

    # ---------- progress helpers: "unlocked" and "completed" are separate
    def is_done(self, idx):
        return str(idx) in self.save["best_times"]

    def is_unlocked(self, idx):
        # open if: first level, cheat is on, already beaten, or the level before it is beaten
        return idx == 0 or self.save.get("cheat_unlock") or self.is_done(idx) or self.is_done(idx - 1)

    def completed_count(self):
        return sum(1 for i in range(len(BIOMES) * 5) if self.is_done(i))

    def goto_sandbox(self):
        self.state = "sandbox"
        self.bg_biome = "sky"
        cx = W // 2
        self.set_menu([
            Button((cx - 330, 220, 300, 110), "Classic", lambda: self.start_sandbox(False),
                   sub="one life - best %d m" % self.save["best_classic"]),
            Button((cx + 30, 220, 300, 110), "Checkpoints", lambda: self.start_sandbox(True),
                   sub="flag every 250 m - best %d m" % self.save["best_checkpoint"], color=(60, 160, 90)),
            Button((30, H - 80, 140, 56), "Back", self.goto_title, color=(110, 110, 125)),
        ], back=self.goto_title)

    def quit(self):
        pygame.quit()
        sys.exit()

    # ================================================== starting runs
    def start_level(self, idx):
        data = self.levels[idx]
        self.ctx = dict(mode="level", idx=idx, bi=idx // 5, lvl=idx % 5 + 1, finish=data["finish"])
        self.setup_run(World.from_data(data))

    def start_sandbox(self, cp):
        w = World()
        self.ctx = dict(mode="sandbox", cp=cp)
        self.endless = EndlessGen(w, random.Random(), cp)
        self.endless.ensure(START_X + W + 1200)
        self.setup_run(w)

    def setup_run(self, world):
        self.state = "play"
        self.paused = False
        self.world = world
        self.world_t = 0
        self.player = Player(START_X)
        self.player.g, _ = biome_phys(world.biome_at(START_X))
        self.cam_x = self.player.x - 280
        self.rts = []
        self.weeds = []
        self.drain_pending()
        self.particles, self.texts = [], []
        self.shake = 0.0
        self.jumps = 0
        self.frames = 0
        self.distance = 0
        self.checkpoint_x = START_X
        self.dead = False
        self.death_timer = 0
        self.death_reason = ""
        self.overlay = False
        self.button_down = False
        self.focus_edit = False
        self.focus_err = 0
        self.bg_biome = world.biome_at(self.cam_x + W / 2)
        self.fade = 0.6
        self.buttons = []

    def drain_pending(self):
        for d in self.world.pending:
            self.rts.append(make_rt(d))
        self.world.pending = []

    def retry(self):
        if self.ctx["mode"] == "level":
            self.start_level(self.ctx["idx"])
        elif self.ctx["cp"]:
            self.respawn()
        else:
            self.start_sandbox(False)

    def respawn(self):
        p = Player(self.checkpoint_x)
        p.g, _ = biome_phys(self.world.biome_at(p.x))
        self.player = p
        self.dead = False
        self.overlay = False
        self.buttons = []
        self.death_timer = 0
        self.weeds = []
        for r in self.rts:
            r.reset()
        self.cam_x = p.x - 280
        self.fade = 0.5

    def end_run(self):
        self.record_sandbox()
        self.goto_sandbox()

    def record_sandbox(self):
        if self.ctx and self.ctx["mode"] == "sandbox":
            key = "best_checkpoint" if self.ctx["cp"] else "best_classic"
            if self.distance > self.save[key]:
                self.save[key] = self.distance
                write_save(self.save)

    # ================================================== input
    def press(self):
        if self.state != "play" or self.paused:
            return
        if self.dead:
            if self.overlay:
                self.retry()
            return
        p = self.player
        if p.state == "air":
            p.grab_buffer = 10   # latch onto a vine if one is within reach in the next few frames
            return
        if p.charging:
            return
        if p.state == "ground" or (p.state == "hang" and abs(p.y - (VINE_BOTTOM + HANG_DROP)) < 1):
            p.charging = True
            p.charge_frames = 0
            self.button_down = True

    def release(self):
        self.button_down = False
        if self.state != "play" or self.dead:
            return
        p = self.player
        if p.charging and p.state in ("ground", "hang"):
            self.do_jump()
        p.charging = False

    def menu_activate(self):
        if self.buttons and 0 <= self.sel < len(self.buttons) and self.buttons[self.sel].enabled:
            self.buttons[self.sel].action()

    def menu_move(self, d):
        if not self.buttons:
            return
        n = len(self.buttons)
        i = self.sel
        for _ in range(n):
            i = (i + d) % n
            if self.buttons[i].enabled:
                self.sel = i
                return

    def menus_active(self):
        return self.state != "play" or self.paused or self.overlay

    def handle_event(self, e):
        if e.type == pygame.QUIT:
            self.quit()
        if e.type == pygame.KEYDOWN:
            if self.state == "cheats":
                ch = getattr(e, "unicode", "") or ""
                if e.key == pygame.K_ESCAPE:
                    self.goto_title()
                elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    self.submit_cheat()
                elif e.key == pygame.K_BACKSPACE:
                    self.cheat_text = self.cheat_text[:-1]
                    self.cheat_msg = ""
                elif ch.isalnum() and len(self.cheat_text) < 20:
                    self.cheat_text += ch.lower()
                    self.cheat_msg = ""
                return
            if self.state == "play" and self.save.get("blueberry") and not self.paused and not self.overlay:
                if self.focus_key(e):
                    return
            if e.key == pygame.K_ESCAPE:
                if self.state == "play" and not self.dead:
                    self.toggle_pause()
                elif self.back:
                    self.back()
                return
            if self.menus_active():
                if e.key in (pygame.K_LEFT, pygame.K_UP, pygame.K_a, pygame.K_w):
                    self.menu_move(-1)
                elif e.key in (pygame.K_RIGHT, pygame.K_DOWN, pygame.K_d, pygame.K_s):
                    self.menu_move(1)
                elif e.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
                    self.menu_activate()
                return
            if e.key in (pygame.K_SPACE, pygame.K_w, pygame.K_UP):
                self.press()
        elif e.type == pygame.KEYUP and e.key in (pygame.K_SPACE, pygame.K_w, pygame.K_UP):
            self.release()
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            if self.menus_active():
                for i, b in enumerate(self.buttons):
                    if b.enabled and b.rect.collidepoint(e.pos):
                        self.sel = i
                        b.action()
                        return
                return
            if self.save.get("blueberry") and self.focus_rect.collidepoint(e.pos):
                self.focus_edit = not self.focus_edit
                self.focus_err = 0
                return
            self.focus_edit = False
            if self.button_rect.collidepoint(e.pos):
                self.press()
        elif e.type == pygame.MOUSEBUTTONUP and e.button == 1:
            self.release()

    def focus_key(self, e):
        """Typing into the in-game Focus box (blueberry cheat). Returns True if the key was used."""
        ch = getattr(e, "unicode", "") or ""
        if ch in "12345" and ch:
            self.save["focus"] = int(ch)
            write_save(self.save)
            self.focus_edit = False
            self.focus_err = 0
            self.texts.append(FloatText("Focus %s" % ch, self.player.x, self.player.y - 110,
                                        FOCUS_COLORS[int(ch)]))
            return True
        if not self.focus_edit:
            return False
        if e.key in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_KP_ENTER):
            self.focus_edit = False
            return True
        if ch and (ch.isalnum() or ch in "-+.,"):
            self.focus_err = 90   # show "type 1-5"
            return True
        return False

    def toggle_pause(self):
        if self.paused:
            self.paused = False
            self.buttons = []
            self.back = None
            return
        self.paused = True
        self.player.charging = False
        cx = W // 2
        exit_label = "End run" if self.ctx["mode"] == "sandbox" else "Level select"
        exit_action = self.end_run if self.ctx["mode"] == "sandbox" else (lambda: self.goto_levels(self.ctx["bi"]))
        self.set_menu([
            Button((cx - 140, 200, 280, 60), "Resume", self.toggle_pause),
            Button((cx - 140, 275, 280, 60), "Restart", self.restart_run, color=(60, 140, 230)),
            Button((cx - 140, 350, 280, 60), exit_label, exit_action, color=(110, 110, 125)),
        ], back=self.toggle_pause)

    def restart_run(self):
        if self.ctx["mode"] == "level":
            self.start_level(self.ctx["idx"])
        else:
            self.record_sandbox()
            self.start_sandbox(self.ctx["cp"])

    # ================================================== gameplay actions
    def do_jump(self):
        p = self.player
        charge = self.effective_charge()
        key = self.world.biome_at(p.x)
        p.g, js = biome_phys(key)
        vx, vy = jump_velocity(charge)
        p.vx, p.vy = vx * js[0] * p.facing, -vy * js[1]
        if p.state == "hang":
            p.exclude = p.vine
            p.vine = None
        else:
            p.exclude = None
        p.state = "air"
        p.plat = None
        p.slide = 0.0
        p.jump_charge = charge
        p.charge_frames = 0
        p.charging = False
        p.flipping = charge >= FLIP_THRESHOLD
        p.spin_rate = -360.0 / max(1, (2 * vy * js[1] / p.g)) * p.facing
        p.angle = 0.0
        self.jumps += 1
        for _ in range(8):
            self.particles.append(Particle(p.x, GROUND_Y, random.uniform(-2, 2) - p.facing,
                                           random.uniform(-2, -0.5), 25, (200, 175, 130), random.uniform(3, 6), 0.1))

    def bounce(self, pad_d):
        p = self.player
        p.state = "air"
        p.g, _ = biome_phys(self.world.biome_at(p.x))
        pvx, pvy = pad_vel(self.world.biome_at(p.x))
        p.vx, p.vy = pvx, -pvy
        p.facing = 1
        p.slide = 0.0
        p.plat = None
        p.exclude = None
        p.flipping = True
        p.spin_rate = -360.0 / (2 * pvy / p.g)
        p.jump_charge = 0.6
        p.charging = False
        for r in self.rts:
            if isinstance(r, Pad) and r.d is pad_d:
                r.squish = 1.0
        for _ in range(10):
            self.particles.append(Particle(p.x, GROUND_Y - 6, random.uniform(-3, 3), random.uniform(-3, -1), 25,
                                           random.choice([WHITE, (255, 220, 120)]), 4, 0.1, "star"))

    def land(self, sup):
        p = self.player
        vx_land = p.vx
        p.state = "ground"
        p.y = GROUND_Y
        p.vx = p.vy = 0.0
        p.angle = 0.0
        p.flipping = False
        p.land_squash = 0.62
        p.exclude = None
        p.plat = sup[1] if sup[0] == "plat" else None
        dust = BIOME_BY_KEY[self.world.biome_at(p.x)]["top_dark"]
        for _ in range(6 + int(p.jump_charge * 10)):
            self.particles.append(Particle(p.x + random.uniform(-10, 10), GROUND_Y, random.uniform(-3, 3),
                                           random.uniform(-2.5, -0.5), 28, dust, random.uniform(3, 7), 0.12))
        if p.jump_charge > 0.6:
            self.shake = max(self.shake, 4)
        if p.plat is None:
            pad = self.world.pad_at(p.x)
            if pad is not None:
                self.bounce(pad)
                return
            if self.world.ice_at(p.x):
                self.start_slide()
            seg = sup[1]
            if min(p.x - seg.x0, seg.x1 - p.x) < 22:
                self.texts.append(FloatText("Close one!", p.x, GROUND_Y - 80, (255, 220, 60)))
            elif p.jump_charge >= FLIP_THRESHOLD:
                self.texts.append(FloatText("Flip!", p.x, GROUND_Y - 80, WHITE))

    def start_slide(self):
        p = self.player
        p.slide = True
        p.slide_t = 0
        p.slide_x0 = p.x
        p.slide_x1 = ice_slide_target(self.world, p.x)
        p.facing = 1

    def grab(self, vine):
        p = self.player
        p.state = "hang"
        p.vine = vine
        p.grab_buffer = 0
        p.vx = p.vy = 0.0
        p.angle = 0.0
        p.flipping = False
        p.charging = False
        self.texts.append(FloatText("Grab!", p.x, VINE_BOTTOM - 60, (170, 255, 140)))

    def kill(self, kind, reason, seg=None):
        p = self.player
        if self.dead:
            return
        self.dead = True
        self.death_timer = 0
        self.death_reason = reason
        p.charging = False
        p.dead_seg = seg
        if kind in ("sink", "croc"):
            p.state = "sink"
            liq = seg.liquid if seg is not None and seg.liquid else "water"
            p.liquid = liq
            p.vy = 1.0 if liq != "lava" else 1.6
            info = LIQUIDS[liq]
            sy = GROUND_Y + 20
            if liq == "lava":
                for _ in range(26):
                    self.particles.append(Particle(p.x + random.uniform(-12, 12), sy, random.uniform(-2, 2),
                                                   random.uniform(-6, -2), 50,
                                                   random.choice([(255, 200, 60), (255, 120, 40), (90, 80, 80)]),
                                                   random.uniform(3, 7), 0.12))
            elif liq == "quicksand":
                for _ in range(16):
                    self.particles.append(Particle(p.x + random.uniform(-12, 12), sy, random.uniform(-2, 2),
                                                   random.uniform(-3, -1), 35, info["light"], random.uniform(3, 6), 0.25))
            else:
                for _ in range(32):
                    self.particles.append(Particle(p.x + random.uniform(-12, 12), sy, random.uniform(-3.5, 3.5),
                                                   random.uniform(-9, -3), 45,
                                                   random.choice([info["light"], WHITE, info["color"]]),
                                                   random.uniform(3, 6), 0.35))
                for r in range(3):
                    self.particles.append(Particle(p.x, sy, 0, 0, 40 + r * 10, WHITE, 6 + r * 6, 0, "ring"))
            self.shake = 6
        elif kind == "fall":
            p.state = "fall"
        elif kind == "burn":
            p.state = "crash"
            p.vx, p.vy = -p.facing * 2.5, -8
            self.shake = 12
            for _ in range(20):
                self.particles.append(Particle(p.x, p.y - 25, random.uniform(-4, 4), random.uniform(-6, -1), 40,
                                               random.choice([(255, 200, 60), (255, 120, 40), (80, 70, 70)]),
                                               random.uniform(4, 8), 0.1))
        else:  # crash
            p.state = "crash"
            p.vx = -p.facing * 3.5
            p.vy = -6
            self.shake = 14
            for _ in range(14):
                self.particles.append(Particle(p.x + p.facing * 10, p.y - 30, random.uniform(-4, 4),
                                               random.uniform(-6, -1), 40,
                                               random.choice([(255, 230, 60), (255, 180, 40), WHITE]),
                                               random.uniform(5, 9), 0.25, "star"))
        p.flipping = False
        if self.ctx["mode"] == "sandbox":
            self.record_sandbox()

    def kill_hazard(self, seg):
        """Player went below ground level at a gap/liquid (or off a platform)."""
        if seg is not None and seg.kind == "liquid":
            liq = LIQUIDS[seg.liquid]
            msg = {"lava": "Too hot! You fell into the lava.",
                   "quicksand": "Glug... the quicksand swallowed you.",
                   "swamp": "Splosh! You fell into the swamp.",
                   "icewater": "Brrr! You fell into freezing water."}.get(seg.liquid, "Splash! You fell in the water.")
            self.kill("sink", msg, seg)
        else:
            b = BIOME_BY_KEY[self.world.biome_at(self.player.x)]
            msg = "You fell off the island!" if b["gap"] == "sky" else "Whoops! You fell into a pit."
            self.kill("fall", msg, seg)

    def crash_into(self, ob):
        self.kill("crash", "Bonk! You hit %s." % OBSTACLE_NAMES.get(ob["kind"], "something"))

    # ================================================== update
    def update(self):
        self.t += 1
        for c in self.clouds:
            c[0] -= c[3]
            if c[0] < -300:
                c[0] = W + random.uniform(100, 400)
                c[1] = random.uniform(30, 200)
        if self.state != "play":
            self.cam_x += 0.6
            self.update_ambient()
            return
        if self.paused:
            return
        self.world_t += 1
        self.frames += 1
        p = self.player
        w = self.world
        t = self.world_t
        keys = pygame.key.get_pressed()

        if p.state == "ground":
            if p.plat is not None:
                dx = plat_x(p.plat, t) - plat_x(p.plat, t - 1)
                p.x += dx
            if p.slide:
                p.slide_t += 1
                k = min(1.0, p.slide_t / ICE_SLIDE_FRAMES)
                old_x = p.x
                p.x = p.slide_x0 + (p.slide_x1 - p.slide_x0) * k * k   # speeds up as you lose grip
                p.walk_phase += 0.1
                self.particles.append(Particle(p.x - 8, GROUND_Y - 2, -(p.x - old_x) * 0.5,
                                               random.uniform(-1.5, -0.3), 18,
                                               random.choice([WHITE, (190, 230, 255)]), 2.5, 0.08))
                if k >= 1.0:
                    p.slide = False
            move = 0
            if not p.charging and not p.slide and not self.dead:
                if keys[pygame.K_LEFT] or keys[pygame.K_a]:
                    move -= 1
                if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
                    move += 1
            p.walking = move != 0
            if move:
                p.facing = move
                nx = p.x + move * WALK_SPEED
                if not w.obstacle_hit(nx, p.y):
                    p.x = nx
                    p.walk_phase += 0.28
            if not p.slide and p.plat is None and not self.dead and w.ice_at(p.x):
                self.start_slide()   # walking onto ice makes you slip too
            if not self.dead:
                if p.plat is not None:
                    if abs(p.x - plat_x(p.plat, t)) > p.plat["w"] / 2:
                        p.vx = 1.5 * p.facing
                        self.kill_hazard(None)
                else:
                    seg = w.segment_at(p.x)
                    if seg is None or seg.kind != "ground":
                        sup = w.plat_at(p.x, t)
                        if sup is not None:
                            p.plat = sup
                        else:
                            p.vx = 1.5 * p.facing
                            self.kill_hazard(seg)
                    else:
                        pad = w.pad_at(p.x)
                        if pad is not None:
                            self.bounce(pad)
            if p.charging and p.state in ("ground",):
                p.charge_frames = min(p.charge_max, p.charge_frames + 1)
                if p.charge_frames >= p.charge_max and self.t % 3 == 0:
                    self.particles.append(Particle(p.x + random.uniform(-18, 18), p.y - random.uniform(0, 45), 0,
                                                   random.uniform(-1.5, -0.5), 22, (255, 240, 120), 3, 0, "star"))
            p.land_squash += (1 - p.land_squash) * 0.18

        elif p.state == "air":
            ev = air_step(w, p, t, p.exclude, can_grab=False)
            if ev is None and p.grab_buffer > 0:
                v = w.vine_grab(p.x, p.y, t, p.exclude, radius=VINE_LATCH_RADIUS)
                if v is not None:
                    ev = ("vine", v)
            p.grab_buffer = max(0, p.grab_buffer - 1)
            if p.flipping:
                p.angle += p.spin_rate
            else:
                p.angle = clamp(-p.vy * 1.8, -22, 22) * p.facing
            if self.t % 2 == 0:
                self.particles.append(Particle(p.x, p.y - 25, 0, 0, 12, WHITE, 3 + 4 * p.jump_charge, 0))
            if ev is not None:
                if ev[0] == "land":
                    self.land(ev[1])
                elif ev[0] == "vine":
                    self.grab(ev[1])
                elif ev[0] == "crash":
                    self.crash_into(ev[1])
                elif ev[0] == "fall":
                    self.kill_hazard(ev[1])

        elif p.state == "hang":
            v = p.vine
            p.x = vine_bx(v, t)
            target = VINE_BOTTOM + HANG_DROP
            if p.y < target:
                p.y = min(target, p.y + 6)
            elif p.y > target:
                p.y = max(target, p.y - 6)
            p.walk_phase += 0.05
            if p.charging:
                p.charge_frames = min(p.charge_max, p.charge_frames + 1)
            keys_l = keys[pygame.K_LEFT] or keys[pygame.K_a]
            keys_r = keys[pygame.K_RIGHT] or keys[pygame.K_d]
            if keys_l and not keys_r:
                p.facing = -1
            elif keys_r and not keys_l:
                p.facing = 1

        elif p.state == "fall":
            p.vy += p.g
            p.x += p.vx * 0.5
            p.y += p.vy
            p.angle += 6 * p.facing
            if p.dead_seg is not None:
                p.x = clamp(p.x, p.dead_seg.x0 + PHW, p.dead_seg.x1 - PHW)
        elif p.state == "sink":
            p.y += p.vy
            p.vy = max(0.6, p.vy * 0.97)
            p.angle += (12 * p.facing - p.angle) * 0.05
            if p.dead_seg is not None:
                p.x = clamp(p.x, p.dead_seg.x0 + PHW, p.dead_seg.x1 - PHW)
            if self.t % 6 == 0 and p.y < H + 40 and p.liquid != "quicksand":
                col = (90, 80, 80) if p.liquid == "lava" else LIQUIDS[p.liquid or "water"]["light"]
                self.particles.append(Particle(p.x + random.uniform(-8, 8), p.y - 40, 0, -1.2, 40, col,
                                               random.uniform(2, 4), -0.02, "ring" if p.liquid != "lava" else "circle"))
        elif p.state == "crash":
            p.vy += 0.5
            p.x += p.vx
            p.y += p.vy
            p.angle += 9 * p.facing
            if p.vy > 0 and p.y >= GROUND_Y:
                sup = w.support_at(p.x, t)
                if sup is not None and p.y < GROUND_Y + 20:
                    p.y = GROUND_Y
                    p.vy = -abs(p.vy) * 0.35
                    p.vx *= 0.6
                    if abs(p.vy) < 1:
                        p.vy = 0
                        p.angle = 90 * -p.facing
                        p.state = "ko"

        # entities
        for r in self.rts:
            r.update(self)
        for wd in self.weeds:
            wd.update(self)
        self.weeds = [wd for wd in self.weeds if wd.alive and wd.x > self.cam_x - 300]
        if not self.dead and p.state in ("ground", "air", "hang"):
            for r in self.rts:
                res = r.hit(self)
                if res:
                    kind, msg = res
                    if kind == "croc":
                        self.kill("croc", msg, w.segment_at(p.x))
                    else:
                        self.kill(kind, msg)
                    break
            if not self.dead:
                for wd in self.weeds:
                    if wd.hits(p):
                        self.kill("crash", "Oof! A tumbleweed bowled you over.")
                        break

        # progress
        if not self.dead:
            self.distance = max(self.distance, int((p.x - START_X) / PPM))
            if self.ctx["mode"] == "level" and p.state == "ground" and p.x >= self.ctx["finish"]:
                self.complete_level()
                return
        else:
            self.death_timer += 1
            if self.death_timer == 75:
                self.show_death_overlay()

        # camera & world streaming
        lead = 280 if p.facing > 0 else 520
        target = p.x - lead
        self.cam_x += (target - self.cam_x) * (0.08 if not self.dead else 0.03)
        if self.ctx["mode"] == "sandbox":
            self.endless.ensure(self.cam_x + W + 1000)
            if self.t % 120 == 0:
                minx = min(self.cam_x, self.checkpoint_x) - 900
                w.prune(minx)
                self.rts = [r for r in self.rts if r.right() > minx]
            self.drain_pending()

        bg = w.biome_at(self.cam_x + W / 2)
        if bg != self.bg_biome:
            self.bg_biome = bg
            self.fade = 1.0
            if self.ctx["mode"] == "sandbox" and not self.dead:
                self.texts.append(FloatText(BIOME_BY_KEY[bg]["name"], p.x + 200, GROUND_Y - 150, (255, 240, 140)))
        self.fade = max(0.0, self.fade - 0.03)

        for part in self.particles:
            part.update()
        self.particles = [q for q in self.particles if q.life > 0]
        if len(self.particles) > 600:
            self.particles = self.particles[-600:]
        for ft in self.texts:
            ft.life -= 1
            ft.y -= 1
        self.texts = [ft for ft in self.texts if ft.life > 0]
        self.shake *= 0.85
        self.update_ambient()

    def show_death_overlay(self):
        self.overlay = True
        cx = W // 2
        if self.ctx["mode"] == "level":
            btns = [Button((cx - 230, 330, 220, 60), "Retry", self.retry),
                    Button((cx + 10, 330, 220, 60), "Levels", lambda: self.goto_levels(self.ctx["bi"]),
                           color=(110, 110, 125))]
            back = lambda: self.goto_levels(self.ctx["bi"])
        elif self.ctx["cp"]:
            btns = [Button((cx - 230, 330, 220, 60), "Respawn", self.retry, color=(60, 160, 90)),
                    Button((cx + 10, 330, 220, 60), "End run", self.end_run, color=(110, 110, 125))]
            back = self.end_run
        else:
            btns = [Button((cx - 230, 330, 220, 60), "New run", self.retry),
                    Button((cx + 10, 330, 220, 60), "Menu", self.end_run, color=(110, 110, 125))]
            back = self.end_run
        self.set_menu(btns, back=back)

    def complete_level(self):
        idx = self.ctx["idx"]
        secs = self.frames / FPS
        key = str(idx)
        old = self.save["best_times"].get(key)
        self.new_best = old is None or secs < old
        if self.new_best:
            self.save["best_times"][key] = round(secs, 2)
        write_save(self.save)
        self.result = dict(time=secs, jumps=self.jumps)
        self.state = "complete"
        cx = W // 2
        if self.completed_count() == len(self.levels):
            self.state = "victory"
            self.set_menu([Button((cx - 230, 380, 220, 60), "Sandbox", self.goto_sandbox, color=(60, 140, 230)),
                           Button((cx + 10, 380, 220, 60), "Menu", self.goto_title, color=(110, 110, 125))],
                          back=self.goto_title)
            return
        nxt = idx + 1
        if nxt >= len(self.levels):   # last level, but some earlier ones aren't beaten yet
            self.set_menu([
                Button((cx - 230, 360, 220, 60), "Retry", lambda: self.start_level(idx)),
                Button((cx + 10, 360, 220, 60), "Levels", lambda: self.goto_levels(idx // 5), color=(110, 110, 125)),
            ], back=lambda: self.goto_levels(idx // 5))
            return
        label = "Next level" if nxt % 5 else "Next biome!"
        self.set_menu([
            Button((cx - 330, 360, 200, 60), label, lambda: self.start_level(nxt), color=(60, 160, 90)),
            Button((cx - 100, 360, 200, 60), "Retry", lambda: self.start_level(idx)),
            Button((cx + 130, 360, 200, 60), "Levels", lambda: self.goto_levels(idx // 5), color=(110, 110, 125)),
        ], back=lambda: self.goto_levels(idx // 5))

    # ================================================== ambient
    def update_ambient(self):
        kind = BIOME_BY_KEY[self.bg_biome]["ambient"]
        if kind != self.ambient_kind:
            self.ambient_kind = kind
            self.ambient = []
            n = {"snow": 90, "embers": 45, "sand": 30, "fireflies": 26}.get(kind, 0)
            for _ in range(n):
                self.ambient.append([random.uniform(0, W), random.uniform(0, H), random.uniform(0, 6.28),
                                     random.uniform(0.5, 1.5)])
        for a in self.ambient:
            if kind == "snow":
                a[1] += 0.8 * a[3]
                a[0] += math.sin(self.t * 0.02 + a[2]) * 0.4 - 0.2
            elif kind == "embers":
                a[1] -= 0.9 * a[3]
                a[0] += math.sin(self.t * 0.03 + a[2]) * 0.5
            elif kind == "sand":
                a[0] -= 7 * a[3]
                a[1] += math.sin(self.t * 0.05 + a[2]) * 0.3
            elif kind == "fireflies":
                a[0] += math.cos(self.t * 0.01 + a[2]) * 0.6
                a[1] += math.sin(self.t * 0.013 + a[2] * 2) * 0.5
            if a[1] > H + 5:
                a[1] = -5
                a[0] = random.uniform(0, W)
            elif a[1] < -5:
                a[1] = H + 5
                a[0] = random.uniform(0, W)
            if a[0] < -20:
                a[0] = W + 20
            elif a[0] > W + 20:
                a[0] = -20

    def draw_ambient(self):
        kind = self.ambient_kind
        scr = self.screen
        for a in self.ambient:
            x, y = int(a[0]), int(a[1])
            if kind == "snow":
                pygame.draw.circle(scr, WHITE, (x, y), int(1 + a[3] * 1.4))
            elif kind == "embers":
                c = (255, int(120 + 80 * math.sin(self.t * 0.1 + a[2]) ** 2), 40)
                pygame.draw.circle(scr, c, (x, y), int(1 + a[3]))
            elif kind == "sand":
                pygame.draw.line(scr, (250, 225, 170), (x, y), (x + int(14 * a[3]), y), 1)
            elif kind == "fireflies":
                if math.sin(self.t * 0.05 + a[2] * 3) > 0:
                    pygame.draw.circle(scr, (230, 255, 120), (x, y), 3)
                    pygame.draw.circle(scr, (250, 255, 200), (x, y), 1)

    # ================================================== drawing: background
    def draw_cloud(self, x, y, s, col=WHITE):
        for dx, dy, r in ((0, 0, 26), (28, -10, 32), (60, 0, 26), (30, 8, 26)):
            pygame.draw.circle(self.screen, col, (int(x + dx * s), int(y + dy * s)), int(r * s))

    def hills_round(self, factor, base, amp, color, freq=0.004):
        pts = [(0, H)]
        for x in range(0, W + 41, 40):
            wx = x + self.cam_x * factor
            y = base + math.sin(wx * freq) * amp + math.sin(wx * freq * 2.75) * amp * 0.45
            pts.append((x, y))
        pts.append((W, H))
        pygame.draw.polygon(self.screen, color, pts)

    def hills_peaks(self, factor, spacing, hmin, hmax, color, cap, seed):
        off = self.cam_x * factor
        k0 = int(math.floor(off / spacing)) - 2
        base = GROUND_Y + 20
        for k in range(k0, k0 + int(W / spacing) + 5):
            cx = k * spacing - off
            hh = hmin + (hmax - hmin) * h01(k, seed)
            wd = spacing * (0.8 + 0.5 * h01(k, seed + 1))
            top = base - hh
            pygame.draw.polygon(self.screen, color, [(cx - wd, base), (cx, top), (cx + wd, base)])
            if cap:
                cw = wd * 0.28
                ch = hh * 0.28
                pts = [(cx, top), (cx + cw, top + ch), (cx + cw * 0.4, top + ch * 0.8), (cx, top + ch * 1.05),
                       (cx - cw * 0.5, top + ch * 0.75), (cx - cw, top + ch)]
                pygame.draw.polygon(self.screen, cap, pts)

    def draw_background(self, key):
        b = BIOME_BY_KEY[key]
        scr = self.screen
        scr.blit(self.sky_cache[key], (0, 0))
        cel = b["celestial"]
        if cel == "sun":
            pygame.draw.circle(scr, (255, 245, 190), (W - 140, 90), 48)
            pygame.draw.circle(scr, (255, 235, 140), (W - 140, 90), 40)
        elif cel == "bigsun":
            pygame.draw.circle(scr, (255, 226, 160), (W - 170, 120), 78)
            pygame.draw.circle(scr, (255, 214, 110), (W - 170, 120), 60)
        elif cel == "palesun":
            pygame.draw.circle(scr, (250, 250, 235), (W - 150, 80), 34)
        elif cel == "redsun":
            pygame.draw.circle(scr, (220, 100, 60), (W - 180, 140), 52)
            pygame.draw.circle(scr, (250, 140, 80), (W - 180, 140), 40)
        elif cel == "earth":
            for x, y, ph, sz in self.stars:
                br = int(160 + 95 * math.sin(self.t * 0.03 + ph) ** 2)
                pygame.draw.circle(scr, (br, br, br), (int(x), int(y)), sz)
            pygame.draw.circle(scr, (50, 110, 220), (W - 160, 100), 42)
            pygame.draw.circle(scr, (70, 170, 90), (W - 172, 90), 16)
            pygame.draw.circle(scr, (70, 170, 90), (W - 145, 115), 11)
            pygame.draw.circle(scr, (240, 245, 255), (W - 150, 78), 8)
        if b["clouds"]:
            col = (255, 255, 255) if key != "mountains" else (240, 244, 252)
            for c in self.clouds:
                x = (c[0] - self.cam_x * 0.05) % (W + 400) - 200
                self.draw_cloud(x, c[1], c[2], col)
        style = b["hills"]
        if style == "round":
            self.hills_round(0.15, 300, 40, b["hill_far"])
            self.hills_round(0.4, 345, 30, b["hill_near"])
        elif style == "dunes":
            self.hills_round(0.12, 315, 34, b["hill_far"], 0.0025)
            self.hills_round(0.35, 352, 24, b["hill_near"], 0.003)
        elif style == "peaks":
            self.hills_peaks(0.12, 180, 160, 260, b["hill_far"], (246, 250, 255), 3)
            self.hills_peaks(0.35, 130, 70, 140, b["hill_near"], (236, 242, 252), 7)
        elif style == "volcano":
            self.hills_peaks(0.12, 260, 150, 230, b["hill_far"], None, 5)
            off = self.cam_x * 0.12
            k0 = int(math.floor(off / 260)) - 2
            for k in range(k0, k0 + 7):
                if h01(k, 5) > 0.6:
                    cx = k * 260 - off
                    top = GROUND_Y + 20 - (150 + 80 * h01(k, 5))
                    glow = int(120 + 80 * math.sin(self.t * 0.05 + k) ** 2)
                    pygame.draw.ellipse(scr, (255, glow, 40), (cx - 14, top - 4, 28, 10))
            self.hills_peaks(0.35, 110, 50, 110, b["hill_near"], None, 9)
        elif style == "trees":
            self.hills_round(0.12, 290, 36, b["hill_far"])
            off = self.cam_x * 0.35
            k0 = int(math.floor(off / 46)) - 2
            for k in range(k0, k0 + int(W / 46) + 5):
                cx = k * 46 - off
                r = 30 + 22 * h01(k, 11)
                cy = 330 - 30 * h01(k, 12)
                pygame.draw.rect(scr, (60, 40, 26), (cx - 5, cy, 10, GROUND_Y - cy + 20))
                pygame.draw.circle(scr, b["hill_near"], (int(cx), int(cy)), int(r))
                pygame.draw.circle(scr, lerp_color(b["hill_near"], (120, 200, 110), 0.3),
                                   (int(cx - r * 0.3), int(cy - r * 0.3)), int(r * 0.45))
        elif style == "moon":
            self.hills_round(0.1, 330, 26, b["hill_far"], 0.003)
            self.hills_round(0.3, 362, 16, b["hill_near"], 0.005)
            off = self.cam_x * 0.3
            k0 = int(math.floor(off / 150)) - 1
            for k in range(k0, k0 + 9):
                cx = k * 150 - off + 60 * h01(k, 3)
                rw = 30 + 30 * h01(k, 4)
                pygame.draw.ellipse(scr, (54, 54, 70), (cx - rw, 372 + 10 * h01(k, 6), rw * 2, rw * 0.35))
        elif style == "sky":
            off = self.cam_x * 0.25
            k0 = int(math.floor(off / 90)) - 2
            for k in range(k0, k0 + int(W / 90) + 5):
                cx = k * 90 - off
                r = 50 + 30 * h01(k, 21)
                pygame.draw.circle(scr, (250, 236, 246), (int(cx), int(H - 20 + 10 * h01(k, 22))), int(r))
            off = self.cam_x * 0.45
            k0 = int(math.floor(off / 70)) - 2
            for k in range(k0, k0 + int(W / 70) + 5):
                cx = k * 70 - off
                r = 40 + 26 * h01(k, 23)
                pygame.draw.circle(scr, WHITE, (int(cx), int(H + 20 - 10 * h01(k, 24))), int(r))
        self.draw_ambient()

    # ================================================== drawing: world
    def draw_ground(self, seg, off):
        sx0 = seg.x0 - self.cam_x + off[0]
        sx1 = seg.x1 - self.cam_x + off[0]
        if sx1 < -10 or sx0 > W + 10:
            return
        b = BIOME_BY_KEY[seg.biome]
        scr = self.screen
        gy = GROUND_Y + off[1]
        w = sx1 - sx0
        if seg.kind == "ground":
            if b["key"] == "sky":
                depth = min(170, 60 + (seg.x1 - seg.x0) * 0.25)
                pts = [(sx0, gy + 8), (sx1, gy + 8), (sx1 - w * 0.12, gy + depth * 0.45),
                       (sx0 + w * 0.55, gy + depth), (sx0 + w * 0.12, gy + depth * 0.45)]
                pygame.draw.polygon(scr, b["dirt"], pts)
                pygame.draw.polygon(scr, b["dirt_dark"], pts, 3)
            else:
                pygame.draw.rect(scr, b["dirt"], (sx0, gy, w, H - gy + 20))
                start = int(seg.x0 // 37) * 37
                for wx in range(start, int(seg.x1), 37):
                    if wx < seg.x0 + 8 or wx > seg.x1 - 8:
                        continue
                    x = wx - self.cam_x + off[0]
                    if -10 < x < W + 10:
                        py = gy + 30 + (wx * 7919) % 90
                        pygame.draw.circle(scr, b["dirt_dark"], (int(x), int(py)), 3)
                pygame.draw.rect(scr, b["dirt_dark"], (sx0, gy + 12, 5, H))
                pygame.draw.rect(scr, b["dirt_dark"], (sx1 - 5, gy + 12, 5, H))
            pygame.draw.rect(scr, b["top_dark"], (sx0, gy, w, 16))
            pygame.draw.rect(scr, b["top"], (sx0, gy, w, 12))
            if b["tufts"] or b["key"] == "mountains":
                start = int(seg.x0 // 22) * 22
                for wx in range(start, int(seg.x1), 22):
                    if wx < seg.x0 + 4 or wx > seg.x1 - 10:
                        continue
                    x = wx - self.cam_x + off[0]
                    if x < -10 or x > W + 10:
                        continue
                    if b["key"] == "mountains":
                        pygame.draw.circle(scr, b["top"], (int(x + 4), int(gy + 1)), 5)
                    else:
                        sway = math.sin(self.t * 0.05 + wx) * 1.5
                        pygame.draw.polygon(scr, b["top"], [(x, gy + 2), (x + 3 + sway, gy - 7), (x + 6, gy + 2)])
        elif seg.kind == "gap":
            if b["gap"] == "sky":
                return
            for i in range(5):
                c = lerp_color(b["dirt_dark"], b["pit"], (i + 1) / 5)
                pygame.draw.rect(scr, c, (sx0, gy + i * 10, w, 10))
            pygame.draw.rect(scr, b["pit"], (sx0, gy + 50, w, H - gy))
        else:
            pygame.draw.rect(scr, b["dirt_dark"], (sx0, gy, w, H - gy + 20))

    def draw_ice(self, off):
        for z in self.world.ice:
            x0 = z[0] - self.cam_x + off[0]
            x1 = z[1] - self.cam_x + off[0]
            if x1 < 0 or x0 > W:
                continue
            gy = GROUND_Y + off[1]
            scr = self.screen
            pygame.draw.rect(scr, (70, 150, 215), (x0, gy - 3, x1 - x0, 15), border_radius=4)
            pygame.draw.rect(scr, (120, 196, 245), (x0 + 2, gy - 1, x1 - x0 - 4, 9), border_radius=3)
            pygame.draw.rect(scr, (215, 240, 255), (x0 + 4, gy, x1 - x0 - 8, 3), border_radius=2)
            # moving glossy shine
            span = max(1, int(z[1] - z[0]))
            shine = x0 + (self.t * 2 + int(z[0])) % (span + 60) - 30
            if x0 < shine < x1 - 12:
                pygame.draw.line(scr, WHITE, (shine, gy + 9), (shine + 12, gy - 2), 3)
            # twinkles
            for i, xx in enumerate(range(int(z[0]) + 14, int(z[1]) - 8, 34)):
                if math.sin(self.t * 0.12 + i * 1.7) > 0.7:
                    sx = xx - self.cam_x + off[0]
                    pygame.draw.line(scr, WHITE, (sx - 4, gy - 6), (sx + 4, gy - 6), 2)
                    pygame.draw.line(scr, WHITE, (sx, gy - 10), (sx, gy - 2), 2)

    def draw_liquid(self, seg, off):
        sx0 = seg.x0 - self.cam_x + off[0]
        w = int(seg.x1 - seg.x0)
        if sx0 + w < -10 or sx0 > W + 10:
            return
        info = LIQUIDS[seg.liquid]
        top = GROUND_Y + 20 + off[1]
        hgt = int(H - top + 30)
        surf = pygame.Surface((w, max(1, hgt)), pygame.SRCALPHA)
        slow = 0.35 if seg.liquid in ("quicksand", "lava") else 1.0
        pts = [(0, hgt)]
        for x in range(0, w + 1, 8):
            wx = seg.x0 + x
            y = 6 + (math.sin(self.t * 0.08 * slow + wx * 0.05) * 3 + math.sin(self.t * 0.05 * slow + wx * 0.11) * 1.5)
            pts.append((x, y))
        pts.append((w, hgt))
        pygame.draw.polygon(surf, info["color"] + (info["alpha"],), pts)
        pygame.draw.lines(surf, info["light"] + (255,), False, pts[1:-1], 3)
        liq = seg.liquid
        if liq in ("water", "icewater"):
            for i in range(w // 50):
                x = (i * 53 + self.t) % max(1, w)
                y = 18 + (i * 29) % 40
                pygame.draw.line(surf, info["light"] + (150,), (x, y), (x + 8, y), 2)
            if liq == "icewater":
                for i in range(w // 90 + 1):
                    x = (i * 97 + seg.x0 * 3) % max(1, w - 30)
                    pygame.draw.polygon(surf, (240, 250, 255, 230), [(x, 8), (x + 22, 6), (x + 28, 12), (x + 4, 14)])
        elif liq == "swamp":
            for i in range(w // 80 + 1):
                x = (i * 83 + seg.x0) % max(1, w - 20) + 10
                pygame.draw.ellipse(surf, (90, 160, 70, 255), (x - 10, 6, 20, 8))
        elif liq == "quicksand":
            for i in range(w // 30 + 1):
                x = (i * 41 + seg.x0) % max(1, w)
                y = 20 + (i * 23) % 50
                pygame.draw.circle(surf, (170, 124, 60, 255), (int(x), int(y)), 3)
        elif liq == "lava":
            for i in range(w // 60 + 1):
                ph = (self.t + i * 37) % 90
                x = (i * 67 + seg.x0) % max(1, w)
                if ph < 30:
                    pygame.draw.circle(surf, (255, 220, 90, 255), (int(x), 10), int(2 + ph / 6), 2)
            for i in range(0, w, 24):
                y = 30 + (i * 13) % 40
                pygame.draw.line(surf, (255, 150, 40, 255), (i, y), (i + 12, y + 4), 2)
        self.screen.blit(surf, (sx0, top - 6))
        if liq == "lava":
            glow = pygame.Surface((w, 40), pygame.SRCALPHA)
            for i in range(8):
                pygame.draw.rect(glow, (255, 120, 40, 8 + i * 5), (0, 40 - (i + 1) * 5, w, 5))
            self.screen.blit(glow, (sx0, top - 46))

    def draw_obstacle(self, o, off):
        x = o["x"] - self.cam_x + off[0]
        if x < -120 or x > W + 120:
            return
        b = BIOME_BY_KEY[o["biome"]]
        scr = self.screen
        kind, ow, oh = o["kind"], o["w"], o["h"]
        gy = GROUND_Y + off[1]
        y = gy - oh
        if kind == "rock":
            n = 9
            pts = []
            for i in range(n + 1):
                a = math.pi * i / n
                r = 1 - h01(o["x"], i) * 0.18
                pts.append((x + (0.5 - 0.5 * math.cos(a) * r) * ow, y + (1 - math.sin(a) * r) * oh))
            col = b["rock"]
            pygame.draw.polygon(scr, col, pts)
            pygame.draw.polygon(scr, lerp_color(col, BLACK, 0.35), pts, 3)
            pygame.draw.circle(scr, lerp_color(col, WHITE, 0.3), (int(x + ow * 0.35), int(y + oh * 0.35)), max(3, ow // 8))
            if b["key"] == "mountains":
                pygame.draw.ellipse(scr, WHITE, (x + ow * 0.2, y - 2, ow * 0.6, 10))
            elif b["key"] == "jungle":
                pygame.draw.ellipse(scr, (80, 150, 60), (x + ow * 0.15, y, ow * 0.5, 9))
        elif kind == "crate":
            for i in range(oh // ow):
                r = pygame.Rect(int(x), int(gy - (i + 1) * ow), ow, ow)
                pygame.draw.rect(scr, (190, 135, 70), r)
                pygame.draw.rect(scr, (120, 80, 40), r, 4)
                pygame.draw.line(scr, (120, 80, 40), r.topleft, r.bottomright, 4)
                pygame.draw.line(scr, (120, 80, 40), r.topright, r.bottomleft, 4)
        elif kind in ("spikes", "icespikes", "crystals"):
            col = b["spike"]
            if kind != "crystals":
                pygame.draw.rect(scr, lerp_color(col, BLACK, 0.5), (x, gy - 6, ow, 6))
            n = max(1, ow // 12)
            step = ow / n
            for i in range(n):
                bx = x + i * step
                hh = oh if kind != "crystals" else oh * (0.6 + 0.4 * h01(o["x"], i))
                tri = [(bx, gy - 3), (bx + step / 2, gy - hh), (bx + step, gy - 3)]
                pygame.draw.polygon(scr, col, tri)
                pygame.draw.polygon(scr, lerp_color(col, BLACK, 0.4), tri, 2)
                if kind != "spikes":
                    pygame.draw.line(scr, WHITE, (bx + step / 2, gy - hh + 4), (bx + step * 0.35, gy - 6), 1)
        elif kind == "cactus":
            g1, g2 = (70, 150, 70), (40, 110, 50)
            pygame.draw.rect(scr, g1, (x, y, ow, oh), border_radius=ow // 2)
            pygame.draw.rect(scr, g2, (x, y, ow, oh), 3, border_radius=ow // 2)
            ay = y + oh * 0.35
            pygame.draw.rect(scr, g1, (x - 12, ay, 14, 10), border_radius=4)
            pygame.draw.rect(scr, g1, (x - 12, ay - 18, 10, 26), border_radius=5)
            ay2 = y + oh * 0.5
            pygame.draw.rect(scr, g1, (x + ow - 2, ay2, 14, 10), border_radius=4)
            pygame.draw.rect(scr, g1, (x + ow + 2, ay2 - 16, 10, 24), border_radius=5)
            for i in range(4):
                pygame.draw.line(scr, (240, 240, 200), (x + 6, y + 10 + i * 12), (x + 2, y + 8 + i * 12), 1)
        elif kind == "thorns":
            dark, mid = (30, 80, 34), (50, 112, 46)
            for i in range(4):
                cx = x + ow * (0.15 + 0.23 * i)
                pygame.draw.circle(scr, mid if i % 2 else dark, (int(cx), int(gy - oh * 0.45)), int(oh * 0.55))
            for i in range(8):
                a = math.pi * (0.1 + 0.8 * i / 7)
                bx = x + ow / 2 - math.cos(a) * ow * 0.5
                by = gy - math.sin(a) * oh
                pygame.draw.polygon(scr, (200, 190, 150), [(bx - 3, by + 4), (bx + 3, by + 4),
                                                           (bx - math.cos(a) * 8, by - math.sin(a) * 8)])

    def draw_world(self, off):
        w = self.world
        lo, hi = self.cam_x - 100, self.cam_x + W + 100
        segs = [s for s in w.segments if s.x1 > lo and s.x0 < hi]
        for s in segs:
            self.draw_ground(s, off)
        self.draw_ice(off)
        for r in self.rts:
            if not r.front:
                r.draw(self, off)
        for o in w.obstacles:
            if lo - 100 < o["x"] < hi:
                self.draw_obstacle(o, off)
        return segs

    def draw_trajectory_hint(self, off):
        p = self.player
        g, js = biome_phys(self.world.biome_at(p.x))
        vx, vy = jump_velocity(self.effective_charge())
        vx *= js[0] * p.facing
        vy = -vy * js[1]
        x, y = p.x, p.y - 25
        steps = max(7, int((2 * -vy / g) * FOCUS_PREVIEW[self.focus_level()]))
        for i in range(steps):
            vy += g
            x += vx
            y += vy
            if i % 3 == 0:
                fade = 1 - i / max(1, steps)
                pygame.draw.circle(self.screen, lerp_color((150, 150, 150), WHITE, fade),
                                   (int(x - self.cam_x + off[0]), int(y + off[1])), 3)

    def draw_player(self, off):
        p = self.player
        if p.y > H + 120:
            return
        dead = p.state in ("crash", "ko", "fall", "sink")
        if p.state == "ground":
            pose = "crouch" if p.charging else ("walk" if p.walking else "stand")
        elif p.state == "air":
            pose = "air"
        elif p.state == "hang":
            pose = "hang"
        elif p.state in ("fall", "sink", "crash"):
            pose = "flail"
        else:
            pose = "stand"
        phase = self.t * 0.3 if pose == "flail" else p.walk_phase
        sprite = build_player_sprite(pose, phase, p.facing, dead=dead)
        sqx = sqy = 1.0
        if p.state in ("ground", "hang") and p.charging:
            sqy = 1 - 0.28 * p.charge
            sqx = 1 + 0.18 * p.charge
        elif p.state == "ground":
            sqy = p.land_squash
            sqx = 2 - p.land_squash
            if not p.walking:
                sqy *= 1 + math.sin(self.t * 0.08) * 0.02
        elif p.state == "air":
            st = clamp(abs(p.vy) / 14, 0, 1) * 0.12
            sqy, sqx = 1 + st, 1 - st * 0.6
        sw, sh = max(1, int(70 * sqx)), max(1, int(90 * sqy))
        img = pygame.transform.smoothscale(sprite, (sw, sh))
        angle = p.angle
        if p.state == "hang":
            angle = -math.cos(self.world_t * 0.03 + p.vine["phase"]) * 6 if p.vine else 0
        if angle:
            img = pygame.transform.rotate(img, angle)
        jitter = random.uniform(-1.5, 1.5) if p.charging and p.charge >= 1 else 0
        sx = p.x - self.cam_x + off[0] + jitter
        sy = p.y + off[1]
        if p.state in ("ground", "air", "crash", "ko") and p.y <= GROUND_Y + 1:
            if self.world.support_at(p.x, self.world_t) is not None:
                height = GROUND_Y - p.y
                sw2 = max(8, 34 - height * 0.08)
                sh_surf = pygame.Surface((int(sw2), 8), pygame.SRCALPHA)
                pygame.draw.ellipse(sh_surf, (0, 0, 0, 70), sh_surf.get_rect())
                self.screen.blit(sh_surf, (sx - sw2 / 2, GROUND_Y + off[1] - 4))
        rect = img.get_rect(center=(int(sx), int(sy - 43 * sqy)))
        f = self.focus_level()
        if f >= 4 and p.state in ("ground", "air", "hang"):
            aura = pygame.Surface((140, 140), pygame.SRCALPHA)
            pulse = 1 + 0.08 * math.sin(self.t * 0.1)
            strength = 40 if f == 4 else 75
            for i in range(6):
                pygame.draw.circle(aura, (120, 200, 255, int(strength * (1 - i / 6))), (70, 70),
                                   int((30 + i * 7) * pulse))
            self.screen.blit(aura, aura.get_rect(center=rect.center))
        self.screen.blit(img, rect)
        if p.charging:
            bw, bh = 56, 9
            bx, by = sx - bw / 2, sy - 90 * sqy - 14
            pygame.draw.rect(self.screen, (30, 30, 40), (bx - 2, by - 2, bw + 4, bh + 4), border_radius=5)
            c = self.effective_charge()
            col = lerp_color((90, 220, 90), (255, 210, 50), c * 2) if c < 0.5 \
                else lerp_color((255, 210, 50), (240, 70, 50), (c - 0.5) * 2)
            if c > 0:
                pygame.draw.rect(self.screen, col, (bx, by, max(2, bw * c), bh), border_radius=4)

    # ================================================== drawing: HUD & screens
    def draw_jump_button(self):
        r = self.button_rect
        p = self.player
        pressed = self.button_down and p.charging
        rr = r.move(0, 4) if pressed else r
        if not pressed:
            pygame.draw.rect(self.screen, (150, 40, 30), r.move(0, 6), border_radius=18)
        pygame.draw.rect(self.screen, (235, 75, 55), rr, border_radius=18)
        ch = self.effective_charge() if p.charging else 0
        if ch > 0:
            fh = max(1, int(rr.h * ch))
            fill_surf = pygame.Surface((rr.w, fh), pygame.SRCALPHA)
            pygame.draw.rect(fill_surf, (255, 220, 70, 170), fill_surf.get_rect(), border_radius=18)
            self.screen.blit(fill_surf, (rr.x, rr.bottom - fh))
        pygame.draw.rect(self.screen, WHITE, rr, 3, border_radius=18)
        label = self.font_med.render("JUMP", True, WHITE)
        self.screen.blit(label, label.get_rect(center=rr.center))
        hint = self.font_small.render("hold & release", True, WHITE)
        self.screen.blit(hint, hint.get_rect(midbottom=(r.centerx, r.top - 6)))

    def shadow_text(self, text, font, pos, color=WHITE, anchor="topleft"):
        s = font.render(text, True, (20, 25, 45))
        r = s.get_rect(**{anchor: (pos[0] + 2, pos[1] + 2)})
        self.screen.blit(s, r)
        s = font.render(text, True, color)
        r = s.get_rect(**{anchor: pos})
        self.screen.blit(s, r)

    def draw_hud(self):
        scr = self.screen
        ctx = self.ctx
        if ctx["mode"] == "level":
            b = BIOMES[ctx["bi"]]
            self.shadow_text("%s - Level %d" % (b["name"], ctx["lvl"]), self.font_med, (20, 16))
            self.shadow_text("Time %s   Jumps %d" % (fmt_time(self.frames / FPS), self.jumps), self.font_small,
                             (22, 54))
            bx, by, bw = W // 2 - 160, 70, 320
            if W - 360 < bx + bw:
                pass
            bx = W - bw - 30
            by = 26
            prog = clamp((self.player.x - START_X) / (ctx["finish"] - START_X), 0, 1)
            pygame.draw.rect(scr, (30, 30, 45), (bx - 3, by - 3, bw + 6, 18), border_radius=9)
            pygame.draw.rect(scr, (80, 210, 110), (bx, by, max(4, bw * prog), 12), border_radius=6)
            pygame.draw.circle(scr, (235, 92, 62), (int(bx + bw * prog), by + 6), 9)
            pygame.draw.circle(scr, WHITE, (int(bx + bw * prog), by + 6), 9, 2)
            pygame.draw.rect(scr, WHITE, (bx + bw - 2, by - 14, 3, 26))
            pygame.draw.rect(scr, BLACK, (bx + bw + 1, by - 14, 12, 8))
            self.shadow_text("%d%%" % int(prog * 100), self.font_small, (bx + bw // 2, by + 32), anchor="center")
        else:
            self.shadow_text("Distance: %d m" % self.distance, self.font_med, (20, 16))
            key = "best_checkpoint" if ctx["cp"] else "best_classic"
            best = max(self.save[key], self.distance)
            self.shadow_text("Best: %d m   Jumps: %d" % (best, self.jumps), self.font_small, (22, 54))
            bname = BIOME_BY_KEY[self.world.biome_at(self.player.x)]["name"]
            self.shadow_text(bname, self.font_small, (W - 24, 20), (255, 240, 160), anchor="topright")
            if ctx["cp"]:
                self.shadow_text("Checkpoint: %d m" % int((self.checkpoint_x - START_X) / PPM), self.font_small,
                                 (W - 24, 48), (150, 255, 170), anchor="topright")
        if self.save.get("blueberry"):
            self.draw_focus_box()
        self.draw_jump_button()
        tip = self.font_small.render("SPACE also works  -  A/D to step  -  ESC pause", True, (240, 236, 220))
        scr.blit(tip, (20, H - 34))

    def draw_focus_box(self):
        """The blueberry cheat's text box: click it, then type a focus level from 1 to 5."""
        scr = self.screen
        r = self.focus_rect
        f = self.focus_level()
        bg = pygame.Surface(r.size, pygame.SRCALPHA)
        pygame.draw.rect(bg, (20, 20, 40, 170), bg.get_rect(), border_radius=10)
        scr.blit(bg, r.topleft)
        lab = self.font_small.render("Focus (1-5)", True, WHITE)
        scr.blit(lab, (r.x + 10, r.y + 13))
        box = pygame.Rect(r.x + 132, r.y + 7, 44, 32)
        pygame.draw.rect(scr, (250, 245, 235), box, border_radius=6)
        border = (180, 120, 255) if self.focus_edit else (110, 110, 140)
        pygame.draw.rect(scr, border, box, 3, border_radius=6)
        if self.focus_edit:
            txt = "|" if (self.t // 30) % 2 == 0 else ""
        else:
            txt = str(f)
        s = self.font_med.render(txt, True, TEXT_DARK)
        scr.blit(s, s.get_rect(center=box.center))
        for i in range(5):
            col = FOCUS_COLORS[f] if i < f else (70, 70, 90)
            pygame.draw.circle(scr, col, (r.x + 192 + i * 12, r.centery), 5)
        if self.focus_edit:
            hint = self.font_small.render("type 1-5", True, (220, 200, 255))
            scr.blit(hint, (r.x + 4, r.bottom + 4))
        if self.focus_err > 0:
            self.focus_err -= 1
            err = self.font_small.render("Focus must be 1-5", True, (255, 110, 90))
            scr.blit(err, (r.x + 4, r.bottom + 24))

    def draw_panel(self, rect, border=(235, 75, 55)):
        pygame.draw.rect(self.screen, (250, 245, 235), rect, border_radius=20)
        pygame.draw.rect(self.screen, border, rect, 5, border_radius=20)

    def dim(self, alpha=140):
        shade = pygame.Surface((W, H), pygame.SRCALPHA)
        shade.fill((10, 10, 30, alpha))
        self.screen.blit(shade, (0, 0))

    def center_text(self, text, font, y, color=TEXT_DARK):
        s = font.render(text, True, color)
        self.screen.blit(s, s.get_rect(center=(W // 2, y)))

    def draw_buttons(self):
        for i, b in enumerate(self.buttons):
            b.draw(self, i == self.sel)

    def draw_game(self):
        off = (random.uniform(-self.shake, self.shake), random.uniform(-self.shake, self.shake)) \
            if self.shake > 0.5 else (0, 0)
        self.draw_background(self.bg_biome)
        segs = self.draw_world(off)
        if self.player.charging:
            self.draw_trajectory_hint(off)
        self.draw_player(off)
        for wd in self.weeds:
            wd.draw(self, off)
        for s in segs:
            if s.kind == "liquid":
                self.draw_liquid(s, off)
        for r in self.rts:
            if r.front:
                r.draw(self, off)
        for part in self.particles:
            part.draw(self.screen, self.cam_x, off)
        for ft in self.texts:
            s = self.font_med.render(ft.text, True, ft.color)
            s.set_alpha(int(255 * ft.life / 70))
            self.screen.blit(s, s.get_rect(center=(int(ft.x - self.cam_x), int(ft.y))))
        f = self.focus_level()
        if f <= 2:
            self.vignette.set_alpha(255 if f == 1 else 130)
            self.screen.blit(self.vignette, (0, 0))
        if self.fade > 0:
            fl = pygame.Surface((W, H), pygame.SRCALPHA)
            fl.fill((255, 255, 255, int(200 * self.fade)))
            self.screen.blit(fl, (0, 0))
        self.draw_hud()

    def draw_menu_backdrop(self, key, title, subtitle=None):
        self.draw_background(key)
        b = BIOME_BY_KEY[key]
        pygame.draw.rect(self.screen, b["dirt"], (0, GROUND_Y + 40, W, H))
        pygame.draw.rect(self.screen, b["top"], (0, GROUND_Y + 40, W, 12))
        self.dim(90)
        self.shadow_text(title, self.font_big, (W // 2, 70), (255, 230, 90), anchor="center")
        if subtitle:
            self.shadow_text(subtitle, self.font_small, (W // 2, 112), WHITE, anchor="center")

    def draw(self):
        st = self.state
        if st == "title":
            self.draw_menu_backdrop("meadow", "")
            bob = math.sin(self.t * 0.06) * 6
            self.shadow_text("LEAP RUNNER", self.font_big, (W // 2, 120 + bob), (255, 230, 90), anchor="center")
            self.shadow_text("Hold to charge, release to leap!", self.font_small, (W // 2, 180), WHITE,
                             anchor="center")
            spr = build_player_sprite("walk", self.t * 0.2, 1)
            self.screen.blit(spr, (120, GROUND_Y - 48))
            self.draw_buttons()
        elif st == "biomes":
            self.draw_menu_backdrop("meadow", "Choose a Biome", "Beat level 5 of a biome to unlock the next one")
            self.draw_buttons()
        elif st == "levels":
            b = BIOMES[self.menu_biome]
            self.draw_menu_backdrop(b["key"], b["name"], b["blurb"])
            self.draw_buttons()
        elif st == "cheats":
            self.draw_menu_backdrop("meadow", "Cheats", "Type a cheat code and press Enter")
            box = pygame.Rect(0, 0, 420, 64)
            box.center = (W // 2, 230)
            pygame.draw.rect(self.screen, (250, 245, 235), box, border_radius=12)
            pygame.draw.rect(self.screen, (150, 90, 200), box, 4, border_radius=12)
            shown = self.cheat_text if self.cheat_show else "*" * len(self.cheat_text)
            cursor = "|" if (self.t // 30) % 2 == 0 else ""
            s = self.font_med.render(shown + cursor, True, TEXT_DARK)
            self.screen.blit(s, s.get_rect(center=box.center))
            if self.cheat_msg:
                col = (240, 90, 70) if self.cheat_msg == "Wrong code" else (60, 200, 90)
                self.shadow_text(self.cheat_msg, self.font_med, (W // 2, 295), col, anchor="center")
            act = self.active_cheats()
            self.shadow_text("Active: " + (", ".join(act) if act else "none"), self.font_small,
                             (W // 2, 440), (255, 240, 160), anchor="center")
            self.draw_buttons()
        elif st == "sandbox":
            self.draw_menu_backdrop("sky", "Sandbox",
                                    "Endless random terrain - a new biome every 400 m")
            self.draw_buttons()
        elif st == "play":
            self.draw_game()
            if self.paused:
                self.dim()
                self.shadow_text("Paused", self.font_big, (W // 2, 130), WHITE, anchor="center")
                self.draw_buttons()
            elif self.overlay:
                self.dim(120)
                panel = pygame.Rect(0, 0, 560, 290)
                panel.center = (W // 2, H // 2 - 20)
                self.draw_panel(panel)
                title = "Try again!" if self.ctx["mode"] == "level" else "Game over"
                self.center_text(title, self.font_big, panel.top + 52, (235, 75, 55))
                self.center_text(self.death_reason, self.font_small, panel.top + 112)
                if self.ctx["mode"] == "level":
                    pct = clamp((self.player.x - START_X) / (self.ctx["finish"] - START_X), 0, 1)
                    line = "You made it %d%% of the way" % int(pct * 100)
                else:
                    line = "Distance: %d m   Best: %d m" % (
                        self.distance, self.save["best_checkpoint" if self.ctx["cp"] else "best_classic"])
                self.center_text(line, self.font_small, panel.top + 146)
                self.draw_buttons()
        elif st in ("complete", "victory"):
            self.draw_game()
            self.dim(130)
            panel = pygame.Rect(0, 0, 640, 320)
            panel.center = (W // 2, H // 2 - 10)
            self.draw_panel(panel, (60, 170, 90))
            if st == "victory":
                self.center_text("YOU WIN!", self.font_big, panel.top + 55, (60, 170, 90))
                self.center_text("You beat every level in Leap Runner!", self.font_med, panel.top + 115)
                self.center_text("Try the Sandbox to chase a distance record.", self.font_small, panel.top + 160)
            else:
                self.center_text("Level Complete!", self.font_big, panel.top + 55, (60, 170, 90))
                res = self.result
                self.center_text("Time %s     Jumps %d" % (fmt_time(res["time"]), res["jumps"]),
                                 self.font_med, panel.top + 120)
                if self.new_best:
                    self.center_text("New best time!", self.font_small, panel.top + 160, (220, 120, 40))
                if (self.ctx["idx"] + 1) % 5 == 0 and self.ctx["idx"] + 1 < len(self.levels):
                    nb = BIOMES[self.ctx["idx"] // 5 + 1]["name"]
                    self.center_text("%s unlocked!" % nb, self.font_small, panel.top + 190, (60, 140, 230))
            self.draw_buttons()

    # ================================================== loop
    def run(self):
        while True:
            for e in pygame.event.get():
                self.handle_event(e)
            self.update()
            self.draw()
            pygame.display.flip()
            self.clock.tick(FPS)


def main():
    pygame.init()
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("Leap Runner")
    Game(screen).run()


if __name__ == "__main__":
    main()