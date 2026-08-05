#!/usr/bin/env python3
"""Save the latest Bazecor backup of the Dygma Defy into this repo: copy the
raw JSON, transcribe it to readable YAML, render one Defy-shaped SVG per layer
and regenerate the README. Committing is left to the caller."""

import glob
import json
import math
import os
import re
import sys

BACKUP_GLOB = os.environ.get(
    "DYGMA_BACKUP_GLOB",
    "/Users/qjoly/Dygma/Backups/Defy/*/*.json",
)
REPO = os.path.dirname(os.path.abspath(__file__))

# ── Keycode table (extracted from Bazecor) ──────────────────────────────────
# Standard HID 4-231, with a short label for the SVG.
HID = {
    40: "Enter", 41: "Esc", 42: "Bksp", 43: "Tab", 44: "Space", 45: "-",
    46: "=", 47: "[", 48: "]", 49: "\\", 50: "#", 51: ";", 52: "'",
    53: "`", 54: ",", 55: ".", 56: "/", 57: "Caps", 100: "\\|", 101: "Menu",
    70: "PrtSc", 71: "ScrLk", 72: "Pause", 73: "Ins", 74: "Home", 75: "PgUp",
    76: "Del", 77: "End", 78: "PgDn", 79: "→", 80: "←", 81: "↓", 82: "↑",
    83: "NumLk", 84: "KP/", 85: "KP*", 86: "KP-", 87: "KP+", 88: "KPEnt",
    99: "KP.", 224: "LCtrl", 225: "LShift", 226: "LAlt", 227: "LGui",
    228: "RCtrl", 229: "RShift", 230: "RAlt", 231: "RGui",
}
for c in range(4, 30):                   # A-Z
    HID[c] = chr(ord("A") + c - 4)
for i, c in enumerate(range(30, 39)):    # 1-9
    HID[c] = str(i + 1)
HID[39] = "0"
for c in range(58, 70):                  # F1-F12
    HID[c] = f"F{c - 57}"
for i, c in enumerate(range(89, 98)):    # KP1-9
    HID[c] = f"KP{i + 1}"
HID[98] = "KP0"

MOD_BIT = [(256, "C"), (512, "A"), (1024, "AGr"), (2048, "S"), (4096, "O")]
DUAL_MOD = {49169: "Ctrl", 49425: "Shift", 49681: "Alt", 49937: "Gui", 50705: "AltGr"}
ONESHOT_MOD = {
    49153: "OSCtrl", 49154: "OSShift", 49155: "OSAlt", 49156: "OSGui",
    49157: "OSCtrl", 49158: "OSShift", 49159: "OSAltGr", 49160: "OSGui",
}
# Bazecor stores consumer keys as <base>+<HID usage>; the low byte is the usage.
MEDIA = {
    22709: "Next", 22710: "Prev", 22711: "Stop", 22712: "Eject", 22713: "Shuffle",
    22733: "Play", 19682: "Mute", 23663: "Camera", 23664: "Bright+", 23665: "Bright-",
    23785: "Vol+", 23786: "Vol-",
}
MOUSE = {
    20481: "M↑", 20482: "M↓", 20484: "M←", 20488: "M→", 20497: "Wh↑",
    20498: "Wh↓", 20500: "Wh←", 20504: "Wh→", 20546: "MBtnL", 20548: "MBtnR",
    20552: "MBtnM", 20560: "MBtnBack", 20576: "Warp",
}
WIRELESS = {54108: "BT Status", 54109: "BT Pair", 54111: "BT Status", 54112: "BT"}

# Short description per layer, keyed by its Bazecor name (kept in the README).
LAYER_DOC = {
    "main": "QWERTY de base. Dual-function sur les pouces "
            "(Bksp/Ctrl, Enter/Alt, Enter/Ctrl). Slot 38 = `Layer Lock 4` → "
            "bascule permanente vers ErgoL.",
    "mouse-zqsd": "Souris (déplacements + clics), navigation (flèches, "
                  "PgUp/PgDn) et pavé numérique.",
    "L3": "Média (Play/Stop/Prev/Next/Vol±/Mute/Shuffle), F1-F12 et macros "
          "(préfixes tmux `Ctrl+B`).",
    "ErgoL": "Layout ErgoL (type Colemak FR) posé sur un OS **US** : lettres "
             "ErgoL + le « chrome » de main (chiffres, Suppr, Shift, pouces). "
             "Slot 38 = `Layer Lock 1` → retour main. Maintenir `Layer Shift 5` "
             "(pouce) → couche Accents.",
    "Accents": "Accents FR via **macros** (touches mortes US-International : "
               "`'`+e=é, `` ` ``+e=è, `^`+e=ê…) + `€` (AltGr+5). Accès en "
               "maintenant le pouce depuis ErgoL.",
}


def decode(code):
    """Return (short label, long description) for a raw keycode."""
    if code == 0:
        return ("", "____ (transparent)")
    if code in (65535, 65534):
        return ("", "disabled")
    if code in HID:
        return (HID[code], HID[code])
    if code in ONESHOT_MOD:
        return (ONESHOT_MOD[code], f"One-shot {ONESHOT_MOD[code]}")
    if code in MEDIA:
        return (MEDIA[code], f"Media {MEDIA[code]}")
    if code in MOUSE:
        return (MOUSE[code], f"Mouse {MOUSE[code]}")
    if code in WIRELESS:
        return (WIRELESS[code], WIRELESS[code])
    if 17450 <= code <= 17459:
        n = code - 17449
        return (f"LS{n}", f"Layer Shift {n}")
    if 49161 <= code <= 49168:
        n = code - 49160
        return (f"OSL{n}", f"One-shot Layer {n}")
    if 17492 <= code <= 17501:
        n = code - 17491
        return (f"LL{n}", f"Layer Lock {n}")
    for base, name in DUAL_MOD.items():          # tap key / hold modifier
        if base <= code < base + 256:
            k = HID.get(code - base, "?")
            return (f"{k}/{name}", f"{k} tap / {name} hold")
    if 51218 <= code < 51218 + 256 * 8:          # tap key / hold layer
        n = (code - 51218) // 256 + 1
        k = HID.get((code - 51218) % 256, "?")
        return (f"{k}/L{n}", f"{k} tap / Layer {n} hold")
    if 256 <= code < 8192:                        # modifier(s) + key (bits 8-12)
        base = code & 0xFF
        mods = [name for bit, name in MOD_BIT if code & bit]
        if mods and base in HID:
            pre = "+".join(mods)
            return (f"{pre}+{HID[base]}", f"{pre} + {HID[base]}")
    if 53853 <= code <= 53979:
        return (f"M{code - 53852}", f"Macro {code - 53852}")
    if 53980 <= code <= 54107:
        return (f"SK{code - 53980 + 1}", f"Superkey {code - 53980 + 1}")
    return (f"#{code}", f"unknown ({code})")


# ── Defy physical geometry (5×16 matrix, split 8|8, 70 keys) ─────────────────
GAPS = {7, 8, 23, 24, 39, 40, 54, 55, 56, 57}

# Columnar stagger (ergonomic bowl): per finger column, from outer pinky (0)
# to inner index (6). X spacing puts the outer column on its own island.
COL_X = [0.0, 1.35, 2.40, 3.45, 4.50, 5.55, 6.55]
COL_Y = [0.62, 0.30, 0.06, -0.14, 0.02, 0.30, 0.60]
HALF_W = COL_X[-1] + 1.0          # width of one half in key units
MIDGAP = 1.6                      # gap between the two halves


def finger_pos(slot):
    """(x, y, angle) for a main-block slot (rows 0-3), left or right half."""
    row, col = divmod(slot, 16)
    if col < 8:                                  # left half, columns 0..6
        c = col
        return (COL_X[c], row + COL_Y[c], 0.0)
    rc = col - 9                                 # right half real column 0..6
    x = HALF_W + MIDGAP + (COL_X[-1] - COL_X[6 - rc])
    return (x, row + COL_Y[6 - rc], 0.0)


THUMB_TILT = 18                  # whole-cluster inward tilt (degrees)
THUMB_LX = 2.7                   # left cluster anchor x
THUMB_RX = HALF_W + MIDGAP + 3.85  # right cluster anchor x
THUMB_Y = 4.55                   # cluster anchor y


def thumb_pos(slot):
    """(x, y, angle) for a thumb-cluster slot: two arcs of 4, fanned like the Defy."""
    row, col = divmod(slot, 16)
    left = col < 8
    idx = col if left else col - 8               # 0..7 within the thumb
    ring, k = divmod(idx, 4)                     # near arc (0), far arc (1)
    lx = k * 1.06                                # step across the arc
    ly = ring * 1.12 + (k - 1.5) ** 2 * 0.10     # shallow smile + second row
    fan = (k - 1.5) * 15                          # per-key fan angle
    if left:
        th = math.radians(THUMB_TILT)
        ax, ang = THUMB_LX, fan + THUMB_TILT
    else:
        lx, fan = -lx, -fan                       # mirror the right cluster
        th = math.radians(-THUMB_TILT)
        ax, ang = THUMB_RX, fan - THUMB_TILT
    x = ax + lx * math.cos(th) - ly * math.sin(th)
    y = THUMB_Y + lx * math.sin(th) + ly * math.cos(th)
    return (x, y, ang)


def slot_pos(slot):
    return thumb_pos(slot) if slot // 16 == 4 else finger_pos(slot)


def render_svg(layer_codes, name, idx):
    U = 58                                        # key size px
    PAD = 26
    positions = {s: (slot_pos(s), c) for s, c in enumerate(layer_codes)
                 if s not in GAPS}
    # bounding box accounting for rotation
    pts = []
    for (x, y, _), _ in positions.values():
        pts += [(x, y), (x + 0.9, y + 0.9)]
    minx = min(p[0] for p in pts)
    miny = min(p[1] for p in pts)
    w = int((max(p[0] for p in pts) - minx) * U + 2 * PAD)
    h = int((max(p[1] for p in pts) - miny) * U + 2 * PAD + 40)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" font-family="ui-monospace,Menlo,monospace">',
        f'<rect width="{w}" height="{h}" rx="16" fill="#171a20"/>',
        f'<text x="{PAD}" y="30" fill="#e8ecf4" font-size="19" '
        f'font-weight="700">Layer {idx} — {esc(name)}</text>',
    ]
    ks = U - 8
    for slot, ((x, y, angle), code) in sorted(positions.items()):
        px = PAD + (x - minx) * U
        py = PAD + 40 + (y - miny) * U
        short, _ = decode(code)
        off = code in (0, 65535, 65534)
        fill = "#20242d" if off else "#2c333f"
        stroke = "#2b2f38" if off else "#4b5468"
        cx, cy = px + ks / 2, py + ks / 2
        rot = f' transform="rotate({angle:.1f} {cx:.1f} {cy:.1f})"' if angle else ""
        out.append(
            f'<rect x="{px:.1f}" y="{py:.1f}" width="{ks}" height="{ks}" '
            f'rx="8" fill="{fill}" stroke="{stroke}" stroke-width="1.5"{rot}/>'
        )
        if short:
            fs = 15 if len(short) <= 3 else (12 if len(short) <= 6 else 9)
            out.append(
                f'<text x="{cx:.1f}" y="{cy + fs / 3:.1f}" text-anchor="middle" '
                f'fill="#e2e7f0" font-size="{fs}"{rot}>{esc(short)}</text>'
            )
    out.append("</svg>")
    return "\n".join(out)


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def yaml_scalar(s):
    """JSON is valid YAML for a scalar → safe quoting."""
    return json.dumps(s, ensure_ascii=False)


def used(layer_codes):
    return any(c not in (0, 65535, 65534) for c in layer_codes)


def main():
    files = glob.glob(BACKUP_GLOB)
    if not files:
        sys.exit(f"No backup found via {BACKUP_GLOB}")
    latest = max(files, key=lambda f: os.path.basename(f))  # name = timestamp
    data = json.load(open(latest))
    codes = next(
        item["data"].split()
        for item in data["backup"] if item["command"] == "keymap.custom"
    )
    codes = list(map(int, codes))
    layers = [codes[i * 80:(i + 1) * 80] for i in range(10)]
    names = {l["id"]: l["name"] for l in data.get("neuron", {}).get("layers", [])}

    # 1. Raw JSON (re-flashable source of truth)
    with open(os.path.join(REPO, "defy.json"), "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # 2. Readable YAML
    ydoc = ["# Generated by sync.py — do not edit by hand.",
            f"source: {yaml_scalar(os.path.basename(latest))}",
            f"neuronID: {yaml_scalar(data.get('neuronID', ''))}",
            "layers:"]
    rendered = []
    os.makedirs(os.path.join(REPO, "layouts"), exist_ok=True)
    for idx, lc in enumerate(layers):
        if not used(lc):
            continue
        nm = names.get(idx, f"layer{idx}")
        ydoc += [f"  - index: {idx}",
                 f"    name: {yaml_scalar(nm)}",
                 "    keys:"]
        for slot, code in enumerate(lc):
            if slot in GAPS:
                continue
            _, desc = decode(code)
            ydoc.append(f"      - {{slot: {slot}, code: {code}, key: {yaml_scalar(desc)}}}")
        slug = re.sub(r"[^a-z0-9]+", "-", nm.lower()).strip("-") or f"layer{idx}"
        path = f"layouts/layer-{idx}-{slug}.svg"
        with open(os.path.join(REPO, path), "w") as f:
            f.write(render_svg(lc, nm, idx))
        rendered.append((idx, nm, path))
    with open(os.path.join(REPO, "layers.yaml"), "w") as f:
        f.write("\n".join(ydoc) + "\n")

    # 3. README
    rd = ["# Dygma Defy — config", "",
          f"Latest backup: `{os.path.basename(latest)}`  ",
          f"neuronID: `{data.get('neuronID', '')}`", "",
          "Généré depuis les backups Bazecor par [`sync.py`](./sync.py) ; "
          "sens inverse (YAML → JSON flashable) via [`restore.py`](./restore.py) "
          "(`mise run restore`).",
          "Source ré-flashable : [`defy.json`](./defy.json) · "
          "transcription lisible : [`layers.yaml`](./layers.yaml).", "",
          "## Layers", ""]
    for idx, nm, path in rendered:
        rd += [f"### Layer {idx} — {nm}", ""]
        if nm in LAYER_DOC:
            rd += [LAYER_DOC[nm], ""]
        rd += [f"![layer {idx}]({path})", ""]
    with open(os.path.join(REPO, "README.md"), "w") as f:
        f.write("\n".join(rd) + "\n")

    print(f"OK: {os.path.basename(latest)} → {len(rendered)} layer(s) rendered")


if __name__ == "__main__":
    main()
