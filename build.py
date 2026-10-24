import os, time, math
import cadquery as cq
from kiosk_v2 import *

OUT = "out"
os.makedirs(OUT + "/stl", exist_ok=True)
os.makedirs(OUT + "/step", exist_ok=True)
BED = (220, 220, 250)

t0 = time.time()
base_L, base_R = split(make_base()); print("base", time.time() - t0)
head_L, head_R = split(make_head()); print("head", time.time() - t0)
roof_L, roof_R = split(make_roof()); print("roof", time.time() - t0)
parts = {
    "01_base_left": (base_L, None),
    "02_base_right": (base_R, None),
    "03_head_left": (head_L, None),
    "04_head_right": (head_R, None),
    "05_roof_left": (roof_L, "flip"),
    "06_roof_right": (roof_R, "flip"),
    "07_rear_access_panel": (make_rear_panel(), "rear"),
    "08_component_tray": (make_tray(), None),
    "09_camera_pod": (make_camera_pod(), "flip"),
    "10_screen_clip_x4": (make_clip(), None),
}
colors = {"base": (0.93, 0.93, 0.91), "head": (0.93, 0.93, 0.91), "roof": (0.93, 0.93, 0.91),
          "rear": (0.75, 0.75, 0.75), "tray": (0.25, 0.45, 0.75), "camera": (0.15, 0.15, 0.15),
          "clip": (0.3, 0.3, 0.3)}

asm = cq.Assembly(name="CEPDT_kiosk_v2")
report = []
for name, (wp, orient) in parts.items():
    shp = wp.val()
    ok = shp.isValid()
    key = next(k for k in colors if k in name)
    if name.startswith("10"):  # clips: show 4 in assembly near screen bosses only as single reference
        pass
    asm.add(wp, name=name, color=cq.Color(*colors[key]))
    cq.exporters.export(wp, f"{OUT}/step/{name}.step")
    # print orientation
    p = shp
    if orient == "flip":
        p = p.rotate((0, 0, 0), (1, 0, 0), 180)
    elif orient == "rear":
        p = p.rotate((0, 0, 0), (1, 0, 0), 90)
    bb = p.BoundingBox()
    p = p.translate((-bb.xmin, -bb.ymin, -bb.zmin))
    bb = p.BoundingBox()
    dims = sorted([bb.xlen, bb.ylen])
    fits = dims[0] <= BED[0] and dims[1] <= BED[1] and bb.zlen <= BED[2]
    cq.exporters.export(cq.Workplane().add(p), f"{OUT}/stl/{name}.stl", tolerance=0.05, angularTolerance=0.15)
    report.append(f"{name:26s} {bb.xlen:6.1f} x {bb.ylen:6.1f} x {bb.zlen:6.1f}  vol {shp.Volume()/1000:7.1f} cm3  valid={ok} fits={fits}")

asm.save(f"{OUT}/kiosk_v2_assembly.step")
print("\n".join(report))
open(f"{OUT}/report.txt", "w").write("\n".join(report))
print("total", time.time() - t0)
