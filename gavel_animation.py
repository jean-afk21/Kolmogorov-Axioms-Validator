# gavel_animation.py
# Reusable gavel impact animation for tkinter (Python 3.8+, no extra packages).
#
# How to use it inside your app (parent = the Text widget that shows results):
#
#     self.gavel = GavelAnimation(self.output)
#     self.gavel.play(valid=True, on_done=self.show_verdict)
#     ...
#     self.gavel.cancel()   # call from Clear, opening history, closing window
#
# The gavel is drawn on a canvas that COVERS its parent (placed with
# place(relwidth=1, relheight=1)), so it never needs extra layout space and
# can never be pushed off-screen. It rescales itself to any window size.
#
# Run this file directly to preview it:   python gavel_animation.py

import math
import random
import threading
import time
import tkinter as tk

# ------------------------------------------------------------------
# BLOCK 1: Settings (change these to tune the feel of the animation)
# ------------------------------------------------------------------
FRAME_MS = 16            # delay between frames (~60 FPS)
WINDUP_MS = 340          # gavel rises
HOLD_MS = 160            # tense pause at the top
SLAM_MS = 110            # very fast swing down
BOUNCE_MS = 280          # small rebound after hitting the block
AFTER_IMPACT_MS = 800    # how long the impact stays on screen

T_SLAM = WINDUP_MS + HOLD_MS          # time when the slam starts
T_IMPACT = T_SLAM + SLAM_MS           # time of the hit
T_END = T_IMPACT + AFTER_IMPACT_MS    # time when the animation finishes

DESIGN_W, DESIGN_H = 400, 300         # we draw at this size, then scale to fit
PIVOT = (322, 192)                    # the gavel swings around this point
REST_DEG, RAISED_DEG = 18, 72         # start angle and fully raised angle
IMPACT_POINT = (160, 220)             # where the head meets the block
SHAKE_PX = 9                          # screen shake strength at the hit
GRAVITY = 900                         # pulls the sparks down

BG = "#16161d"
OUTLINE = "#2a170b"
PALETTES = {
    True:  {"sparks": ["#ffd23f", "#ff9f1c", "#ffffff"], "ring": "#ffe58a"},
    False: {"sparks": ["#ff4d5a", "#ff8a5c", "#ffffff"], "ring": "#ff9aa2"},
}



# ------------------------------------------------------------------
# BLOCK 2: Small math helpers (easing curves, colors, rotation)
# ------------------------------------------------------------------
def lerp(a, b, t):
    return a + (b - a) * t


def clamp01(t):
    return max(0.0, min(1.0, t))


def ease_out_cubic(t):
    """Fast start, slow end (used for the rise and the shockwave)."""
    return 1 - (1 - t) ** 3


def ease_in_cubic(t):
    """Slow start, very fast end (used for the slam, so it feels heavy)."""
    return t ** 3


def blend(c1, c2, t):
    """Mix two '#rrggbb' colors. t=0 gives c1, t=1 gives c2."""
    t = clamp01(t)
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(lerp(x, y, t)) for x, y in zip(a, b))


def rotate_point(x, y, cx, cy, deg):
    """Rotate (x, y) around (cx, cy). Positive deg lifts the gavel head."""
    rad = math.radians(deg)
    dx, dy = x - cx, y - cy
    return (cx + dx * math.cos(rad) - dy * math.sin(rad),
            cy + dx * math.sin(rad) + dy * math.cos(rad))


def rounded_rect(x1, y1, x2, y2, r, n=5):
    """Points of a rectangle with rounded corners (so it can be rotated)."""
    pts = []
    corners = [(x2 - r, y1 + r, -90), (x2 - r, y2 - r, 0),
               (x1 + r, y2 - r, 90), (x1 + r, y1 + r, 180)]
    for cx, cy, start in corners:
        for i in range(n + 1):
            a = math.radians(start + 90 * i / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


# ------------------------------------------------------------------
# BLOCK 2b: Gavel artwork (original cartoon-style design, side view)
# Drawn for a gavel lying flat (0 degrees) in the 400x300 design space.
# The head's bottom edge sits at y=220, which is the top of the sound block.
# Each part is (points, fill color, outline color); "" means no outline.
# Change the colors in WOOD to re-paint everything.
# ------------------------------------------------------------------
WOOD = {"head": "#a86a3a", "cap": "#8a5230", "handle": "#c98a52",
        "light": "#d9a066", "block": "#8a5a34", "base": "#6b4423",
        "gold": "#f2c94c", "gold_light": "#fff0a8"}

HEAD_PARTS = [
    (rounded_rect(144, 176, 176, 208, 4), WOOD["head"], OUTLINE),          # barrel
    (rounded_rect(148, 179, 153, 205, 2, 3), WOOD["light"], ""),           # shine
    (rounded_rect(136, 164, 184, 180, 6), WOOD["cap"], OUTLINE),           # top cap
    (rounded_rect(142, 166, 178, 169.5, 1.7, 3), WOOD["light"], ""),
    (rounded_rect(136, 204, 184, 220, 6), WOOD["cap"], OUTLINE),           # striking cap
    (rounded_rect(142, 206, 178, 209.5, 1.7, 3), WOOD["light"], ""),
    (rounded_rect(139, 183, 181, 201, 3), WOOD["gold"], OUTLINE),          # gold band
    (rounded_rect(143, 185.5, 150, 198.5, 2, 3), WOOD["gold_light"], ""),  # band shine
]
HANDLE_PARTS = [
    ([(190, 185), (304, 187), (304, 197), (190, 199)], WOOD["handle"], OUTLINE),
    ([(194, 186.5), (302, 188.3), (302, 189.8), (194, 188)], WOOD["light"], ""),
    (rounded_rect(179, 182, 192, 202, 3), WOOD["gold"], OUTLINE),          # collar
    (rounded_rect(298, 181, 328, 203, 8), WOOD["cap"], OUTLINE),           # knob
    (rounded_rect(305, 184, 321, 187.5, 1.7, 3), WOOD["light"], ""),
]
# outlines used for the motion trail while slamming
GHOST_SHAPES = [rounded_rect(136, 164, 184, 220, 6),
                [(190, 185), (304, 187), (304, 197), (190, 199)]]
# sound block
BLOCK_BASE = rounded_rect(98, 238, 222, 254, 4)
BLOCK_TOP = rounded_rect(108, 220, 212, 240, 5)
BLOCK_SHINE = rounded_rect(114, 223, 206, 227, 2, 3)


def _beep():
    """Low thud on impact. Runs in a thread so it never freezes the window."""
    try:
        import winsound
        winsound.Beep(170, 110)
    except Exception:
        pass  # no sound device / not Windows: silently skip


# ------------------------------------------------------------------
# BLOCK 3: The animation class
# ------------------------------------------------------------------
class GavelAnimation:
    def __init__(self, parent, clock=time.perf_counter):
        self.parent = parent
        self.clock = clock               # replaceable clock (used for testing)
        self.canvas = tk.Canvas(parent, bg=BG, highlightthickness=0, bd=0)
        self._after_id = None
        self._running = False
        self._rng = random.Random()
        self._sparks = []
        self._impact_fired = False
        self._start = 0.0
        self.valid = True
        self.sound = True
        self.on_done = None

    # ---------- public API ----------
    @property
    def running(self):
        return self._running

    def play(self, valid=True, on_done=None, sound=True):
        """Show the overlay and play once. on_done() is called when finished."""
        self.cancel()
        self.valid = valid
        self.sound = sound
        self.on_done = on_done
        self._sparks = []
        self._impact_fired = False
        self._running = True
        self.canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.canvas.tk.call("raise", self.canvas._w)
        self._start = self.clock()
        self._tick()

    def cancel(self):
        """Stop immediately, hide the overlay, and do NOT call on_done."""
        if self._after_id is not None:
            try:
                self.canvas.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        self._running = False
        self.on_done = None
        self._hide()

    # ---------- internal: timing loop ----------
    def _hide(self):
        try:
            self.canvas.place_forget()
        except tk.TclError:
            pass

    def _tick(self):
        self._after_id = None
        if not self._running:
            return
        t = (self.clock() - self._start) * 1000.0   # ms since play()
        try:
            self._draw(t)
        except tk.TclError:                          # window was destroyed
            self._running = False
            return
        if t >= T_END:
            self._finish()
        else:
            self._after_id = self.canvas.after(FRAME_MS, self._tick)

    def _finish(self):
        self._running = False
        self._hide()
        callback, self.on_done = self.on_done, None
        if callback:
            callback()

    # ---------- internal: motion ----------
    @staticmethod
    def _angle(t):
        """Gavel angle in degrees at time t (ms)."""
        if t < WINDUP_MS:                            # 1. rise
            return lerp(REST_DEG, RAISED_DEG, ease_out_cubic(t / WINDUP_MS))
        if t < T_SLAM:                               # 2. tense little tremble
            q = (t - WINDUP_MS) / HOLD_MS
            return RAISED_DEG + 1.6 * math.sin(t / 12.0) * (1 - q)
        if t < T_IMPACT:                             # 3. slam down
            p = (t - T_SLAM) / SLAM_MS
            return RAISED_DEG * (1 - ease_in_cubic(p))
        since = t - T_IMPACT
        if since < BOUNCE_MS:                        # 4. rebound
            q = since / BOUNCE_MS
            return 15 * math.sin(math.pi * q) * (1 - 0.5 * q)
        return 0.0

    def _fire_impact(self):
        """Runs once, on the first frame after the hit."""
        self._impact_fired = True
        palette = PALETTES[self.valid]["sparks"]
        for _ in range(26):
            ang = math.radians(self._rng.uniform(205, 335))   # upward fan
            speed = self._rng.uniform(140, 420)
            self._sparks.append({
                "vx": math.cos(ang) * speed,
                "vy": math.sin(ang) * speed,
                "life": self._rng.uniform(350, 650),
                "size": self._rng.uniform(2.0, 4.5),
                "color": self._rng.choice(palette),
            })
        if self.sound:
            threading.Thread(target=_beep, daemon=True).start()

    # ---------- internal: drawing ----------
    def _draw(self, t):
        c = self.canvas
        w, h = c.winfo_width(), c.winfo_height()
        if w < 20 or h < 20:                         # not laid out yet
            w, h = DESIGN_W, DESIGN_H
        s = min(w / DESIGN_W, h / DESIGN_H)          # responsive scale factor
        since = t - T_IMPACT
        hit = since >= 0
        pal = PALETTES[self.valid]

        if hit and not self._impact_fired:
            self._fire_impact()

        # screen shake: random offset that fades out quickly after the hit
        shake_x = shake_y = 0.0
        if hit:
            amp = SHAKE_PX * s * math.exp(-since / 110.0)
            shake_x = self._rng.uniform(-amp, amp)
            shake_y = self._rng.uniform(-amp, amp)
        ox = (w - DESIGN_W * s) / 2 - 10 * s + shake_x
        oy = (h - DESIGN_H * s) / 2 + 10 * s + shake_y

        def P(x, y):                                 # design -> screen coords
            return (ox + x * s, oy + y * s)

        def poly(pts, deg=0.0, **kw):
            flat = []
            for x, y in pts:
                if deg:
                    x, y = rotate_point(x, y, PIVOT[0], PIVOT[1], deg)
                flat.extend(P(x, y))
            return c.create_polygon(flat, **kw)

        # white flash on impact: the background flickers bright, then fades
        flash = clamp01(1 - since / 90.0) if hit else 0.0
        c.configure(bg=blend(BG, "#ffffff", flash * 0.85))
        c.delete("all")

        lw = max(1, round(2 * s))                    # line width

        # floor shadow and sound block
        c.create_oval(*P(92, 247), *P(228, 265), fill="#1f1f29", outline="")
        poly(BLOCK_BASE, fill=WOOD["base"], outline=OUTLINE, width=lw)
        poly(BLOCK_TOP, fill=WOOD["block"], outline=OUTLINE, width=lw)
        poly(BLOCK_SHINE, fill=WOOD["light"], outline="")

        # motion-trail outlines while slamming
        deg = self._angle(t)
        if T_SLAM <= t < T_IMPACT + 20:
            for k in (3, 2, 1):
                trail = blend(WOOD["head"], BG, 0.25 * k)
                for shape in GHOST_SHAPES:
                    poly(shape, deg + 9 * k, fill="", outline=trail, width=lw)

        # the gavel itself (handle first, then head on top)
        for pts, fill, outline in HANDLE_PARTS + HEAD_PARTS:
            poly(pts, deg, fill=fill, outline=outline, width=lw)

        if hit:
            self._draw_impact(c, P, s, since, pal)

    def _draw_impact(self, c, P, s, since, pal):
        cx, cy = IMPACT_POINT

        # flat shockwave on the table + a quick round ring
        if since < 420:
            q = since / 420.0
            r = 10 + 130 * ease_out_cubic(q)
            x1, y1 = P(cx - r, cy - r * 0.3)
            x2, y2 = P(cx + r, cy + r * 0.3)
            c.create_oval(x1, y1, x2, y2, outline=pal["ring"],
                          width=max(1, round((8 * (1 - q) + 1) * s)))
        if since < 240:
            q = since / 240.0
            r = 6 + 75 * ease_out_cubic(q)
            x1, y1 = P(cx - r, cy - r)
            x2, y2 = P(cx + r, cy + r)
            c.create_oval(x1, y1, x2, y2, outline="#ffffff",
                          width=max(1, round((5 * (1 - q) + 1) * s)))

        # sparks flying up and falling back with gravity
        ts = since / 1000.0
        for sp in self._sparks:
            if since >= sp["life"]:
                continue
            x = cx + sp["vx"] * ts
            y = cy + sp["vy"] * ts + 0.5 * GRAVITY * ts * ts
            r = max(0.8, sp["size"] * (1 - since / sp["life"]))
            x1, y1 = P(x - r, y - r)
            x2, y2 = P(x + r, y + r)
            c.create_oval(x1, y1, x2, y2, fill=sp["color"], outline="")


# ------------------------------------------------------------------
# BLOCK 4: Preview window (only runs when you execute this file directly)
# ------------------------------------------------------------------
def _demo():
    root = tk.Tk()
    root.title("Gavel preview (try resizing the window!)")
    root.geometry("520x380")
    text = tk.Text(root, font=("Consolas", 11), wrap="word")
    text.pack(fill="both", expand=True)
    bar = tk.Frame(root)
    bar.pack(fill="x")
    gavel = GavelAnimation(text)
    buttons = []

    def run(valid):
        text.delete("1.0", "end")
        text.insert("end", "Axiom 1: PASS\nAxiom 2: PASS\nAxiom 3: PASS\n")
        for b in buttons:
            b.config(state="disabled")

        def done():
            text.insert("end", "\nVERDICT: VALID" if valid else "\nVERDICT: INVALID")
            for b in buttons:
                b.config(state="normal")

        gavel.play(valid=valid, on_done=done)

    buttons.append(tk.Button(bar, text="Play (valid)", command=lambda: run(True)))
    buttons.append(tk.Button(bar, text="Play (invalid)", command=lambda: run(False)))
    for b in buttons:
        b.pack(side="left", padx=4, pady=4)
    root.mainloop()


if __name__ == "__main__":
    _demo()
