"""
CEPDT Lab Component Kiosk - v2 (print-ready, sectioned)
Parametric CadQuery model. Every printable part fits a 220 x 220 x 250 mm bed.

Coordinates: X = width (left->right), Y = depth (front y=0 -> back), Z = up.
Run:  python kiosk_v2.py   -> writes STEP/STL per part + assembly into ./out
"""
import math
import cadquery as cq

# ---------------- PARAMETERS ----------------
W, D, H = 300.0, 210.0, 450.0     # overall envelope (depth reduced from 300 so halves fit the bed)
T = 4.0                           # wall thickness (printed)
ZB = 210.0                        # top of lower bay / bottom of head
TF = 5.0                          # head floor thickness
RT = 5.0                          # roof thickness
HT = H - RT                       # top of head walls
TILT = 18.0                       # screen tilt back from vertical (deg)
SEAM = W / 2                      # left/right split plane
SCREEN_W, SCREEN_H = 220.0, 140.0 # display module size
WIN_W, WIN_H = 210.0, 128.0       # visible window (smaller than module so it rests on the bezel)
SCREEN_T = 8.0                    # display module thickness -> clip boss height
TRAY_W, TRAY_D, TRAY_H = 210.0, 180.0, 24.0
M3_CLR, M3_INSERT, M3_TAP = 3.4, 4.2, 2.8

ta, ca, sa = math.tan(math.radians(TILT)), math.cos(math.radians(TILT)), math.sin(math.radians(TILT))
N_OUT = cq.Vector(0, -ca, sa)     # outward normal of slanted front face


def box(x0, x1, y0, y1, z0, z1):
    return cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0, centered=False).translate((x0, y0, z0))


def cyl_z(x, y, z0, h, d):
    return cq.Workplane("XY").circle(d / 2).extrude(h).translate((x, y, z0))


def cyl_x(x0, x1, y, z, d):
    return cq.Workplane("YZ").circle(d / 2).extrude(x1 - x0).translate((x0, y, z))


def cyl_y(x, y0, y1, z, d):
    return cq.Workplane("XZ").circle(d / 2).extrude(-(y1 - y0)).translate((x, y0, z))


def slant_plane(x, s, inset=0.0):
    """Plane on the slanted front face. s = distance up the slope from the head bottom edge.
    local X = world X, local Y = up the slope, normal = outward."""
    o = cq.Vector(x, s * sa, ZB + s * ca) - N_OUT * inset
    return cq.Workplane(cq.Plane(origin=o, xDir=(1, 0, 0), normal=N_OUT))


def front_y(z):          # outer slanted face y at height z (head only)
    return (z - ZB) * ta


def seam_holes(points_x_dir):
    """M3 bolt holes across the seam with head counterbore on left, nut trap on right."""
    cut = None
    for (y, z) in points_x_dir:
        c = cyl_x(SEAM - 9, SEAM + 9, y, z, M3_CLR)
        c = c.union(cyl_x(SEAM - 9, SEAM - 5, y, z, 6.2))                       # screw head
        nut = (cq.Workplane("YZ").polygon(6, 6.4).extrude(4).translate((SEAM + 5, y, z)))
        c = c.union(nut)                                                        # M3 nut trap
        cut = c if cut is None else cut.union(c)
    return cut


# =========================================================
# LOWER BAY (tray compartment)  z 0..ZB
# =========================================================
def make_base():
    b = box(0, W, 0, D, 0, ZB).edges("|Z").fillet(6)
    b = b.cut(box(T, W - T, -1, D - T, T, ZB + 1))              # open front + open top
    # corner columns (head screws into heat-set inserts on top)
    cols = [(T, T + 12, 6, 18), (W - T - 12, W - T, 6, 18),
            (T, T + 12, D - T - 12, D - T), (W - T - 12, W - T, D - T - 12, D - T)]
    for x0, x1, y0, y1 in cols:
        b = b.union(box(x0, x1, y0, y1, 0, ZB))
        b = b.cut(cyl_z((x0 + x1) / 2, (y0 + y1) / 2, ZB - 9, 10, M3_INSERT))
    # tray side guides (tall) + tray support ribs (low)
    for x0 in (SEAM - TRAY_W / 2 - 4, SEAM + TRAY_W / 2 + 1):
        b = b.union(box(x0, x0 + 3, 10, D - T, T, T + 18))
    for xc in (70, 230):
        b = b.union(box(xc - 4, xc + 4, 15, D - T, T, T + 7))
    # seam ribs: floor (under the tray) + back wall (full height)
    b = b.union(box(SEAM - 8, SEAM + 8, 15, D - T, T, T + 7))
    b = b.union(box(SEAM - 8, SEAM + 8, D - T - 8, D - T, 0, ZB))
    b = b.cut(seam_holes([(40, T + 3.5), (110, T + 3.5), (180, T + 3.5),
                          (D - T - 4, 40), (D - T - 4, 110), (D - T - 4, 185)]))
    # rubber-foot recesses (12 mm bumpons)
    for x, y in [(22, 22), (W - 22, 22), (22, D - 22), (W - 22, D - 22)]:
        b = b.cut(cyl_z(x, y, -1, 2.5, 13))
    # cable notch at back-bottom (optional mains/USB lead for lighting)
    return b


# =========================================================
# HEAD (display + electronics)  z ZB..HT, open top (roof is separate)
# =========================================================
def wedge(z0, z1, inset_front=0.0, x0=0, x1=W, yback=D):
    """Prism with slanted front, from z0 to z1."""
    pts = [(front_y(z0) + inset_front / ca, z0), (yback, z0), (yback, z1), (front_y(z1) + inset_front / ca, z1)]
    return (cq.Workplane("YZ").polyline(pts).close().extrude(x1 - x0).translate((x0, 0, 0)))


def make_head():
    h = wedge(ZB, HT)
    try:
        h = h.edges("|Z or |X").edges(">Y").fillet(5)
    except Exception:
        pass
    h = h.cut(wedge(ZB + TF, HT + 1, inset_front=T, x0=T, x1=W - T, yback=D - T))

    # ---- screen bezel ----
    s_win = 138.0
    h = h.cut(slant_plane(SEAM, s_win).rect(WIN_W + 14, WIN_H + 14).extrude(-1.5, combine=False))  # cosmetic recess
    h = h.cut(slant_plane(SEAM, s_win).rect(WIN_W, WIN_H).extrude(-20, combine=False))             # window
    # clip bosses (screen held from inside by 4 printed clips)
    for dx in (-SCREEN_W / 2 - 8, SCREEN_W / 2 + 8):
        for ds in (-SCREEN_H / 2 + 25, SCREEN_H / 2 - 25):
            boss = slant_plane(SEAM + dx, s_win + ds, inset=T).circle(5).extrude(-SCREEN_T, combine=False)
            hole = slant_plane(SEAM + dx, s_win + ds, inset=T).circle(M3_TAP / 2).extrude(-SCREEN_T - 1, combine=False)
            h = h.union(boss).cut(hole)

    # ---- control strip (below screen) ----
    s_c = 34.0
    h = h.cut(slant_plane(60, s_c).rect(66, 34).extrude(-1.2, combine=False))                   # NFC zone
    for x in (114, 134):
        h = h.cut(slant_plane(x, s_c + 4).circle(2.6).extrude(-10, combine=False))            # 5 mm LEDs
    for i in range(7):                                                                          # buzzer grille
        ang = 2 * math.pi * i / 6
        dx, ds = (0, 0) if i == 6 else (6 * math.cos(ang), 6 * math.sin(ang))
        h = h.cut(slant_plane(185 + dx, s_c + ds).circle(1.25).extrude(-10, combine=False))
    h = h.cut(slant_plane(245, s_c + 4).circle(8.1).extrude(-10, combine=False))              # 16 mm button
    labels = [("NFC / QR LOGIN", 60, s_c - 23, 5.0), ("PWR", 114, s_c - 8, 3.8), ("SCAN", 134, s_c - 8, 3.8),
              ("CONFIRM", 245, s_c - 12, 4.2)]
    for txt, x, s, fs in labels:
        try:
            t = slant_plane(x, s).text(txt, fs, -0.6, combine=False, halign="center", valign="center", kind="bold")
            h = h.cut(t)
        except Exception as e:
            print("label skipped:", txt, e)

    # ---- head floor: camera, LED channel, screw counterbores ----
    h = h.cut(cyl_z(SEAM, 30, ZB - 1, TF + 2, 12))                      # camera cable
    for x in (SEAM - 16, SEAM + 16):
        h = h.cut(cyl_z(x, 30, ZB - 1, TF + 2, M3_CLR))                 # camera pod screws
    h = h.cut(box(30, W - 30, 46, 58, ZB - 1, ZB + 2))                  # LED strip channel (underside)
    h = h.cut(cyl_z(26, 52, ZB - 1, TF + 2, 6))                         # LED cable
    for x, y in [(T + 6, 12), (W - T - 6, 12), (T + 6, D - T - 6), (W - T - 6, D - T - 6)]:
        h = h.cut(cyl_z(x, y, ZB - 1, TF + 2, M3_CLR)).cut(cyl_z(x, y, ZB + TF - 3, 4, 6.5))

    # ---- Raspberry Pi 5 standoffs (right half) ----
    px, py = 182.0, 118.0
    for dx in (3.5, 61.5):
        for dy in (3.5, 52.5):
            h = h.union(cyl_z(px + dx, py + dy, ZB + TF, 6, 6.5)).cut(cyl_z(px + dx, py + dy, ZB + TF - 1, 8, 2.5))
    # generic M3 boss grid for PSU / USB hub (left half)
    for x in (40, 110):
        for y in (110, 170):
            h = h.union(cyl_z(x, y, ZB + TF, 5, 8)).cut(cyl_z(x, y, ZB + TF, 6, M3_INSERT))

    # ---- columns for roof screws ----
    for x0, x1, y0, y1 in [(T, T + 10, 95, 105), (W - T - 10, W - T, 95, 105),
                           (T, T + 12, D - T - 12, D - T), (W - T - 12, W - T, D - T - 12, D - T)]:
        h = h.union(box(x0, x1, y0, y1, ZB, HT))
        h = h.cut(cyl_z((x0 + x1) / 2, (y0 + y1) / 2, HT - 9, 10, M3_INSERT))

    # ---- rear access opening (right half) + insert pads ----
    ox0, ox1, oz0, oz1 = 165, 265, ZB + 25, ZB + 205
    for x in (159, 271):
        for z in (ZB + 19, ZB + 211):
            h = h.union(box(x - 5, x + 5, D - T - 6, D - T, z - 5, z + 5))
    h = h.cut(box(ox0, ox1, D - T - 1, D + 1, oz0, oz1))
    for x in (159, 271):
        for z in (ZB + 19, ZB + 211):
            h = h.cut(cyl_y(x, D - 9, D + 1, z, M3_INSERT))

    # ---- side vents ----
    for i in range(6):
        z = ZB + 110 + i * 14
        h = h.cut(box(-1, W + 1, 120, 190, z, z + 4))

    # ---- seam ribs ----
    h = h.union(box(SEAM - 8, SEAM + 8, 45, D - T, ZB + TF, ZB + TF + 8))   # floor
    h = h.union(box(SEAM - 8, SEAM + 8, D - T - 8, D - T, ZB, HT))          # back wall
    for s0, s1 in ((6, 60), (212, 246)):                                     # slanted front, below/above window
        rib = slant_plane(SEAM, (s0 + s1) / 2, inset=T).rect(16, s1 - s0).extrude(-8, combine=False)
        h = h.union(rib.intersect(wedge(ZB + TF, HT)))
    pts = [(60, ZB + TF + 4), (120, ZB + TF + 4), (180, ZB + TF + 4),
           (D - T - 4, ZB + 40), (D - T - 4, ZB + 120), (D - T - 4, ZB + 200)]
    for s in (33, 229):
        p = cq.Vector(0, s * sa, ZB + s * ca) - N_OUT * (T + 4)
        pts.append((p.y, p.z))
    h = h.cut(seam_holes(pts))
    return h


# =========================================================
# ROOF (two halves)
# =========================================================
def make_roof():
    r = wedge(HT, H)
    try:
        r = r.edges("|X").edges(">Z").fillet(3)
    except Exception:
        pass
    r = r.union(box(SEAM - 8, SEAM + 8, front_y(HT) + 14, D - T - 9, HT - 8, HT))   # seam rib underneath
    r = r.cut(seam_holes([(110, HT - 4), (170, HT - 4)]))
    for x, y in [(T + 5, 100), (W - T - 5, 100), (T + 6, D - T - 6), (W - T - 6, D - T - 6)]:
        r = r.cut(cyl_z(x, y, HT - 1, RT + 2, M3_CLR)).cut(cyl_z(x, y, H - 2.5, 3, 6.5))
    return r


# =========================================================
# SMALL PARTS
# =========================================================
def make_rear_panel():
    x0, x1, z0, z1 = 153, 277, ZB + 13, ZB + 217
    p = box(x0, x1, D, D + 3, z0, z1).edges("|Y").fillet(4)
    for x in (159, 271):
        for z in (ZB + 19, ZB + 211):
            p = p.cut(cyl_y(x, D - 1, D + 4, z, M3_CLR))
    for i in range(7):                                         # vent slots
        z = ZB + 95 + i * 14
        p = p.cut(box(180, 250, D - 1, D + 4, z, z + 5))
    p = p.cut(box(193, 237, D - 1, D + 4, ZB + 40, ZB + 56))   # USB-C power + USB-A cut-out
    p = p.cut(cyl_y(215, D - 1, D + 4, ZB + 75, 8))            # spare (DC jack / cable gland)
    return p


def make_tray():
    x0 = SEAM - TRAY_W / 2
    y0 = 20.0
    z0 = T + 7
    t = box(x0, x0 + TRAY_W, y0, y0 + TRAY_D, z0, z0 + TRAY_H).edges("|Z").fillet(6)
    t = t.cut(box(x0 + 2.4, x0 + TRAY_W - 2.4, y0 + 2.4, y0 + TRAY_D - 2.4, z0 + 2.4, z0 + TRAY_H + 1)
              .edges("|Z").fillet(4))
    t = t.cut(cyl_y(SEAM, y0 - 1, y0 + 4, z0 + TRAY_H, 36))    # finger pull notch
    return t


def make_camera_pod():
    """Mounts under head floor; holds a 32 x 32 mm USB camera board tilted 25 deg toward the tray."""
    plate = box(SEAM - 24, SEAM + 24, 17, 43, ZB - 4, ZB)
    cup = box(-20, 20, -20, 20, -14, 0)                       # local, top at z=0
    cup = cup.rotate((0, 0, 0), (1, 0, 0), -25).translate((SEAM, 30, ZB - 10))
    stem = box(SEAM - 14, SEAM + 14, 20, 40, ZB - 14, ZB - 4)
    pod = plate.union(stem).union(cup)
    pocket = box(-16.6, 30, -16.6, 16.6, -11, -3).rotate((0, 0, 0), (1, 0, 0), -25).translate((SEAM, 30, ZB - 10))
    lens = cq.Workplane("XY").circle(7).extrude(20).translate((0, 0, -25)).rotate((0, 0, 0), (1, 0, 0), -25) \
        .translate((SEAM, 30, ZB - 10))
    pod = pod.cut(pocket).cut(lens)
    pod = pod.cut(box(SEAM + 8, SEAM + 20, 24, 36, ZB - 20, ZB + 1))   # cable path up
    pod = pod.cut(cyl_z(SEAM, 30, ZB - 5, 6, 12))
    for x in (SEAM - 16, SEAM + 16):
        pod = pod.cut(cyl_z(x, 30, ZB - 15, 16, M3_CLR))
    return pod


def make_clip():
    c = box(0, 30, 0, 10, 0, 3).edges("|Z").fillet(2)
    return c.cut(cyl_z(5, 5, -1, 5, M3_CLR))


def split(part):
    big = 1000
    left = part.intersect(box(-big, SEAM, -big, big, -big, big))
    right = part.intersect(box(SEAM, big, -big, big, -big, big))
    return left, right
