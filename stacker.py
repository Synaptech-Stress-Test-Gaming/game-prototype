"""
Animal Stacker prototype (single file).

Controls
    SPACE / left click  drop the hovering sprite (and replay on the game-over screen)
    F (hold)            raise mock "focus" (stand-in for an EEG signal)
    R                   reset at any time
    ESC                 quit

Requires: pygame, pymunk   (py -m pip install pygame pymunk)
"""

import math
import os
import random
import sys

import pygame
import pymunk

# --- Tunables -----------------------------------------------------------------
FPS = 60
SUBSTEPS = 4                    # physics steps per frame
GRAVITY = 1400.0                # px / s^2 (y points down)
FRICTION = 0.9
DENSITY = 0.002                 # mass per px^2, same for every sprite

PLATFORM_WIDTH_FRAC = 0.30      # platform width as a fraction of screen width
PLATFORM_THICKNESS = 30
PLATFORM_Y_FRAC = 0.80          # platform top, as a fraction of screen height

HOVER_GAP = 140                 # px between top of stack and bottom of hovering sprite
HOVER_MARGIN = 120              # how far past the platform edges the sprite swings
SPEED_AT_ZERO_FOCUS = 900.0     # px / s
SPEED_AT_FULL_FOCUS = 180.0     # px / s

FOCUS_RISE = 0.6                # per second while F is held
FOCUS_DECAY = 0.25              # per second otherwise

REST_LIN_VEL = 4.0              # px / s, below this counts as "stopped"
REST_ANG_VEL = 0.05             # rad / s
REST_TIME = 0.35                # s the sprite must stay below both thresholds
MIN_FALL_TIME = 0.2             # ignore the zero-velocity instant right after release

CAMERA_TOP_MARGIN = 160         # keep hovering sprite at least this far below screen top

BG = (24, 26, 33)
PLATFORM_COLOR = (90, 96, 110)
TEXT = (230, 232, 238)
DIM = (140, 145, 160)
FOCUS_LOW = (220, 90, 80)
FOCUS_HIGH = (90, 200, 130)
SHAPE_COLORS = {
    "rect": (236, 177, 89),
    "circle": (110, 170, 235),
    "triangle": (200, 120, 210),
}


# --- Sprite templates -----------------------------------------------------------
class Template:
    """Geometry of a sprite in its local frame, before it becomes a physics body."""

    def __init__(self, kind):
        self.kind = kind
        self.color = SHAPE_COLORS[kind]
        if kind == "rect":
            w = random.randint(60, 140)
            h = random.randint(35, 80)
            self.verts = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
        elif kind == "circle":
            self.radius = random.randint(25, 45)
        else:
            base = random.randint(70, 130)
            height = random.randint(55, 100)
            apex = random.uniform(-0.35, 0.35) * base   # allow scalene triangles
            # Shift so the centroid sits at the origin; pymunk computes the true
            # centre of gravity from density regardless, this just centres the art.
            pts = [(-base / 2, height), (base / 2, height), (apex, 0)]
            cx = sum(p[0] for p in pts) / 3
            cy = sum(p[1] for p in pts) / 3
            self.verts = [(x - cx, y - cy) for x, y in pts]

    def half_extents(self):
        if self.kind == "circle":
            return self.radius, self.radius
        xs = [v[0] for v in self.verts]
        ys = [v[1] for v in self.verts]
        return max(abs(min(xs)), max(xs)), max(ys)  # (half width, distance origin->bottom)

    def top_offset(self):
        """Distance from the origin up to the top of the shape (unrotated)."""
        if self.kind == "circle":
            return self.radius
        return -min(v[1] for v in self.verts)

    def build(self, space, pos):
        body = pymunk.Body()            # mass/moment/centre of gravity come from shape density
        body.position = pos
        if self.kind == "circle":
            shape = pymunk.Circle(body, self.radius)
        else:
            shape = pymunk.Poly(body, self.verts, radius=0)
        shape.density = DENSITY
        shape.friction = FRICTION
        shape.elasticity = 0.0          # perfectly inelastic
        space.add(body, shape)
        return body, shape


# --- Game -----------------------------------------------------------------------
class Game:
    def __init__(self, screen):
        self.screen = screen
        self.W, self.H = screen.get_size()
        self.font = pygame.font.SysFont("segoeui,arial", 30)
        self.big_font = pygame.font.SysFont("segoeui,arial", 84, bold=True)
        self.focus = 0.0
        self.reset()

    # ---- state ----
    def reset(self):
        self.space = pymunk.Space()
        self.space.gravity = (0, GRAVITY)
        self.space.iterations = 30

        pw = self.W * PLATFORM_WIDTH_FRAC
        self.platform_top = self.H * PLATFORM_Y_FRAC
        self.platform_left = (self.W - pw) / 2
        self.platform_right = self.platform_left + pw
        static = self.space.static_body   # infinite mass, unaffected by gravity
        plat = pymunk.Poly(static, [
            (self.platform_left, self.platform_top),
            (self.platform_right, self.platform_top),
            (self.platform_right, self.platform_top + PLATFORM_THICKNESS),
            (self.platform_left, self.platform_top + PLATFORM_THICKNESS),
        ], radius=0)
        plat.friction = FRICTION
        plat.elasticity = 0.0
        self.space.add(plat)
        self.platform_shape = plat

        self.sprites = []           # list of (body, shape, color)
        self.score = 0
        self.game_over = False
        self.camera_y = 0.0         # world y shown at the top of the screen
        self.falling = None         # body most recently released
        self.fall_time = 0.0
        self.rest_time = 0.0
        self.spawn_hover()

    def stack_top(self):
        """Smallest world y (visually highest point) of everything resting on the platform."""
        top = self.platform_top
        for _, shape, _ in self.sprites:
            top = min(top, shape.bb.bottom)  # pymunk's bb.bottom is the min-y edge
        return top

    def spawn_hover(self):
        self.hover = Template(random.choice(["rect", "circle", "triangle"]))
        _, below = self.hover.half_extents()
        self.hover_y = self.stack_top() - HOVER_GAP - below
        self.hover_x = self.W / 2
        speed = SPEED_AT_ZERO_FOCUS + (SPEED_AT_FULL_FOCUS - SPEED_AT_ZERO_FOCUS) * self.focus
        self.hover_vx = speed * random.choice((-1, 1))

    def drop(self):
        body, shape = self.hover.build(self.space, (self.hover_x, self.hover_y))
        body.velocity = (0, 0)
        body.angular_velocity = 0
        self.sprites.append((body, shape, self.hover.color))
        self.hover = None
        self.falling = body
        self.fall_time = 0.0
        self.rest_time = 0.0

    # ---- update ----
    def update(self, dt, f_held):
        if f_held:
            self.focus += FOCUS_RISE * dt
        else:
            self.focus -= FOCUS_DECAY * dt
        self.focus = max(0.0, min(1.0, self.focus))

        if self.game_over:
            return

        if self.hover is not None:
            half_w, _ = self.hover.half_extents()
            lo = max(half_w, self.platform_left - HOVER_MARGIN)
            hi = min(self.W - half_w, self.platform_right + HOVER_MARGIN)
            self.hover_x += self.hover_vx * dt
            if self.hover_x < lo:
                self.hover_x = lo + (lo - self.hover_x)
                self.hover_vx = abs(self.hover_vx)
            elif self.hover_x > hi:
                self.hover_x = hi - (self.hover_x - hi)
                self.hover_vx = -abs(self.hover_vx)

        h = dt / SUBSTEPS
        for _ in range(SUBSTEPS):
            self.space.step(h)

        # Lose if any sprite is entirely below the platform's top surface.
        for _, shape, _ in self.sprites:
            if shape.bb.bottom > self.platform_top:
                self.game_over = True
                self.falling = None
                self.hover = None
                return

        if self.falling is not None:
            self.fall_time += dt
            b = self.falling
            still = b.velocity.length < REST_LIN_VEL and abs(b.angular_velocity) < REST_ANG_VEL
            if self.fall_time > MIN_FALL_TIME and still:
                self.rest_time += dt
            else:
                self.rest_time = 0.0
            if self.rest_time >= REST_TIME:
                self.falling = None
                self.score += 1
                self.spawn_hover()

        # Camera follows the tower upward (never below its starting position).
        if self.hover is not None:
            target = min(0.0, self.hover_y - self.hover.top_offset() - CAMERA_TOP_MARGIN)
        else:
            target = self.camera_y
        self.camera_y += (target - self.camera_y) * min(1.0, 10.0 * dt)

    # ---- drawing ----
    def to_screen(self, p):
        return (p[0], p[1] - self.camera_y)

    def draw_template(self, t, x, y):
        if t.kind == "circle":
            c = self.to_screen((x, y))
            pygame.draw.circle(self.screen, t.color, c, t.radius)
            pygame.draw.line(self.screen, BG, c, (c[0] + t.radius, c[1]), 3)
        else:
            pts = [self.to_screen((x + vx, y + vy)) for vx, vy in t.verts]
            pygame.draw.polygon(self.screen, t.color, pts)

    def draw(self):
        s = self.screen
        s.fill(BG)

        if self.hover is not None:
            # Faint guide line straight down from the hovering sprite, behind the stack.
            gx, gy = self.to_screen((self.hover_x, self.hover_y))
            pygame.draw.line(s, (50, 54, 66), (gx, gy), (gx, self.H), 1)

        pts = [self.to_screen(v) for v in self.platform_shape.get_vertices()]
        pygame.draw.polygon(s, PLATFORM_COLOR, pts)

        for body, shape, color in self.sprites:
            if isinstance(shape, pymunk.Circle):
                c = self.to_screen(body.local_to_world(shape.offset))
                r = shape.radius
                pygame.draw.circle(s, color, c, r)
                edge = self.to_screen(body.local_to_world((r, 0)))
                pygame.draw.line(s, BG, c, edge, 3)   # shows rotation
            else:
                pts = [self.to_screen(body.local_to_world(v)) for v in shape.get_vertices()]
                pygame.draw.polygon(s, color, pts)

        if self.hover is not None:
            self.draw_template(self.hover, self.hover_x, self.hover_y)

        self.draw_hud()
        if self.game_over:
            self.draw_game_over()

    def draw_hud(self):
        s = self.screen
        s.blit(self.font.render(f"Score  {self.score}", True, TEXT), (40, 30))

        # Focus bar
        x, y, w, h = 40, 85, 300, 22
        pygame.draw.rect(s, (55, 58, 70), (x, y, w, h), border_radius=6)
        col = tuple(int(a + (b - a) * self.focus) for a, b in zip(FOCUS_LOW, FOCUS_HIGH))
        if self.focus > 0:
            pygame.draw.rect(s, col, (x, y, max(4, int(w * self.focus)), h), border_radius=6)
        s.blit(self.font.render(f"Focus  {self.focus:.2f}", True, TEXT), (x + w + 20, y - 8))

        hint = "SPACE / click: drop    hold F: focus    R: reset    ESC: quit"
        s.blit(self.font.render(hint, True, DIM), (40, self.H - 60))

    def draw_game_over(self):
        s = self.screen
        shade = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 160))
        s.blit(shade, (0, 0))
        lines = [
            (self.big_font, "GAME OVER", TEXT),
            (self.font, f"Score: {self.score}", TEXT),
            (self.font, "SPACE / click to play again", DIM),
        ]
        y = self.H / 2 - 110
        for font, text, color in lines:
            img = font.render(text, True, color)
            s.blit(img, img.get_rect(midtop=(self.W / 2, y)))
            y += img.get_height() + 20

    # ---- input ----
    def on_action(self):
        if self.game_over:
            self.reset()
        elif self.hover is not None:
            self.drop()


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
    pygame.display.set_caption("Animal Stacker")
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
                elif event.key == pygame.K_r:
                    game.reset()
                elif event.key == pygame.K_SPACE:
                    game.on_action()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                game.on_action()

        dt = min(clock.tick(FPS) / 1000.0, 1 / 30)   # clamp so a hitch can't explode physics
        game.update(dt, pygame.key.get_pressed()[pygame.K_f])
        game.draw()
        pygame.display.flip()


if __name__ == "__main__":
    main()
