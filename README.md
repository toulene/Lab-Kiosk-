# Lab Kiosk

A component issue/return kiosk for an electronics lab: a Raspberry Pi 4 model B with a Pi Camera photographs
the parts on a tray, an object-detection model (RF-DETR) identifies and counts them, and the result
is shown on an admin website.

## Repository layout
| Folder | What it is | Runs on |
|---|---|---|
| `prototype/` | Working demo: tray photo → labeller → live admin page | Pi + laptop |
| `images/kiosk_app/` | Full kiosk app (card login, issue/return, stock, admin) using an offline ONNX model | Pi |
| `images/*.ps1`, `images/*.py` | Dataset pipeline: frames from video, auto-labelling, merging public datasets, training, testing | Laptop / GPU PC |
| `kiosk_v2.py`, `build.py`, `stl/`, `step/` | 3D-printed enclosure (CadQuery source + exports) | — |

Datasets, video frames and trained weights are not in git (several GB) - they live locally and on Roboflow.

## Prototype quick start
**Laptop** (admin website): double-click `prototype/start_admin.bat`, or `py prototype/admin_server.py`,
then open http://localhost:5050. It prints the address the Pi should send to.

**Raspberry Pi**: copy the `prototype/` files to `~/kiosk-proto`, then
```bash
cd ~/kiosk-proto && bash setup_pi.sh http://<laptop-ip>:5050   # installs, asks for API keys, tests camera + laptop
./scan.sh                                                       # Enter = scan the tray, q = quit
```
API keys are typed into the setup prompt and stored only on the Pi in `~/kiosk-proto/.env` (never in git).
Labellers - pick one with `KIOSK_LABELLER` in `.env`:
- `rf_label.py` - our trained RF-DETR model on Roboflow: counts + boxes (`ROBOFLOW_API_KEY`, `ROBOFLOW_MODEL`)
- `gem.py` - Groq vision model: component types only (`GROQ_API_KEY`)
- `gem_gemini.py` - Google Gemini: component types only (`GEMINI_API_KEY`)

## Dataset and model
`images/merge_datasets.ps1` merges our own frames (`dataset_v2`) with 13 public Roboflow Universe datasets
into `dataset_v3` (10 classes: arduino_mega, arduino_uno, diode, disk_cap, electrolytic_cap, esp32, led,
mosfet, resistor, transistor), renaming classes via `images/class_map.csv`. The public datasets are
CC BY 4.0 - links are in `class_map.csv`. Train with Roboflow or locally with `images/train_rfdetr.py`.

## Enclosure (3D-printed, sectioned)

Envelope: 300 W x 210 D x 450 H mm. Every part fits a 220 x 220 x 250 mm bed (Ender-3 class or bigger).
Screen tilt: 18 deg back from vertical. Display bay: 220 x 140 mm module, 210 x 128 mm visible window.

### Parts (STL folder is already in print orientation)
| # | Part | Qty | Print notes |
|---|------|-----|-------------|
| 01/02 | Base left / right (tray bay) | 1 each | Upright, no supports |
| 03/04 | Head left / right (screen + electronics) | 1 each | Upright (floor on bed). Supports ONLY under the top edge of the screen window |
| 05/06 | Roof left / right | 1 each | Top face down, no supports |
| 07 | Rear access panel | 1 | Flat |
| 08 | Component tray 210 x 180 x 24 | 1 | No supports |
| 09 | Camera pod (32 x 32 mm USB cam board) | 1 | Supports inside the board pocket |
| 10 | Screen clip | 4 | Flat |

Suggested: PLA/PETG, 0.2 mm layers, 3 walls, 15 % gyroid infill. Estimated filament ~2.3 kg total.

### Hardware
- M3 x 20 bolts + M3 nuts for the seam joints: ~21 (nut traps are on the right-hand halves)
- M3 heat-set inserts (OD ~4.2 mm, 5-6 mm long): 4 base columns, 4 roof columns, 4 rear panel, 4 PSU/hub bosses
- M3 x 10 screws: 4 head-to-base, 4 roof, 4 rear panel, 4 screen clips (self-tap into bosses), 2 camera pod (+ nuts)
- M2.5 x 6 screws: 4 for Raspberry Pi 5
- 4 x 12 mm self-adhesive rubber feet (recesses in base)
- 16 mm momentary push button, 2 x 5 mm LEDs, 12 mm buzzer, NFC reader (PN532/RC522) behind the "NFC / QR LOGIN" zone, LED strip (10 mm wide) in the channel under the head floor

### Assembly order
1. Bolt base left + right (floor rib + back rib). Stick rubber feet.
2. Press heat-set inserts into the 4 base column tops.
3. Bolt head left + right. Fit screen from inside, hold with 4 clips.
4. Fit button, LEDs, buzzer, NFC reader, Pi 5, PSU/hub inside the head. Route camera + LED cables through floor holes.
5. Screw the camera pod and LED strip under the head floor.
6. Lower the head onto the base, 4 x M3 through the head floor into the column inserts.
7. Bolt roof halves together, screw onto the head columns. Fit rear access panel.
8. Slide tray in on the rails.

Edit parameters at the top of kiosk_v2.py (pip install cadquery, then python build.py) to change sizes, wall thickness or tilt.

## License
MIT - see [LICENSE](LICENSE). The public training datasets are not included in this repository; they belong
to their authors under CC BY 4.0 and are credited with links in `images/class_map.csv`.
