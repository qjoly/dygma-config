#!/usr/bin/env python3
"""Sauvegarde le dernier backup Bazecor du Dygma Defy dans ce repo :
   copie le JSON brut, le transcrit en YAML lisible, rend un SVG par layer,
   régénère le README puis commit (push si un remote existe)."""

import glob
import json
import os
import re
import subprocess
import sys

BACKUP_GLOB = os.environ.get(
    "DYGMA_BACKUP_GLOB",
    "/Users/qjoly/Dygma/Backups/Defy/*/*.json",
)
REPO = os.path.dirname(os.path.abspath(__file__))

# ── Table des keycodes (extraite de Bazecor) ────────────────────────────────
# HID standard 4-231. On garde une étiquette courte pour le SVG.
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
for c in range(4, 30):           # A-Z
    HID[c] = chr(ord("A") + c - 4)
for i, c in enumerate(range(30, 39)):  # 1-9
    HID[c] = str(i + 1)
HID[39] = "0"
for c in range(58, 70):          # F1-F12
    HID[c] = f"F{c - 57}"
for i, c in enumerate(range(89, 98)):  # KP1-9
    HID[c] = f"KP{i + 1}"
HID[98] = "KP0"

MOD_BIT = [(256, "C"), (512, "A"), (1024, "AGr"), (2048, "S"), (4096, "O")]
DUAL_MOD = {49169: "Ctrl", 49425: "Shift", 49681: "Alt", 49937: "Gui", 50705: "AltGr"}
ONESHOT_MOD = {
    49153: "OSCtrl", 49154: "OSShift", 49155: "OSAlt", 49156: "OSGui",
    49157: "OSCtrl", 49158: "OSShift", 49159: "OSAltGr", 49160: "OSGui",
}
MEDIA = {
    22709: "Mute", 22710: "Next", 22711: "Prev", 22712: "Vol-", 22713: "Calc",
    22733: "Stop", 23663: "Camera", 23664: "Bright+", 23665: "Bright-",
    23785: "Play", 23786: "Vol+",
}
MOUSE = {
    20481: "M↑", 20482: "M↓", 20484: "M←", 20488: "M→", 20497: "Wh↑",
    20498: "Wh↓", 20500: "Wh←", 20504: "Wh→", 20546: "MBtnL", 20548: "MBtnR",
    20552: "MBtnM", 20560: "MBtnBack", 20576: "Warp",
}
WIRELESS = {54108: "BT Status", 54109: "BT Pair", 54111: "BT Status", 54112: "BT"}


def decode(code):
    """Retourne (label court, description longue) pour un keycode brut."""
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
    # dual-use "tap key / hold modifier"
    for base, name in DUAL_MOD.items():
        if base <= code < base + 256:
            k = HID.get(code - base, "?")
            return (f"{k}/{name}", f"{k} tap / {name} hold")
    # dual-use "tap key / hold layer"
    if 51218 <= code < 51218 + 256 * 8:
        n = (code - 51218) // 256 + 1
        k = HID.get((code - 51218) % 256, "?")
        return (f"{k}/L{n}", f"{k} tap / Layer {n} hold")
    # modifier(s) + key (bits 8-12)
    if 256 <= code < 8192:
        base = code & 0xFF
        mods = [name for bit, name in MOD_BIT if code & bit]
        if mods and base in HID:
            pre = "+".join(mods)
            return (f"{pre}+{HID[base]}", f"{'+'.join(mods)} + {HID[base]}")
    if 53853 <= code <= 53979:
        return (f"M{code - 53852}", f"Macro {code - 53852}")
    if 53980 <= code <= 54107:
        return (f"SK{code - 53980 + 1}", f"Superkey {code - 53980 + 1}")
    return (f"#{code}", f"unknown ({code})")


# ── Géométrie physique du Defy (matrice 5×16, 8|8, 70 touches) ───────────────
GAPS = {7, 8, 23, 24, 39, 40, 54, 55, 56, 57}
# léger stagger ergonomique par colonne (index de colonne 0..6 par demi)
STAGGER = [0.30, 0.22, 0.06, 0.0, 0.06, 0.16, 0.32]
MIDGAP = 2.2   # espace entre les deux moitiés (en unités de touche)


def slot_pos(slot):
    """(x, y) en unités de touche pour un slot 0-79, ou None si gap/thumb géré à part."""
    row, col = divmod(slot, 16)
    left = col < 8
    if row < 4:  # rangées principales
        if left:
            c = col                      # 0..7 (7 = gap)
            x, yoff = c, STAGGER[c] if c < 7 else 0
        else:
            c = col - 8                  # 0..7 (0 = gap côté droit)
            rc = c - 1                   # colonne réelle droite 0..6
            x = 8 + MIDGAP + rc
            yoff = STAGGER[6 - rc]
        return (x, row + yoff)
    # rangée pouce (row 4) : 8 touches par côté en cluster 2×4, incliné vers le centre
    idx = col if left else col - 8       # 0..7
    tr, tc = divmod(idx, 4)              # 2 rangées de 4
    if left:
        x = 3.4 + tc + tr * 0.5
    else:
        x = 8 + MIDGAP + 0.6 - tc + tr * 0.5 + 3
    y = 4.5 + tr * 1.0
    return (x, y)


def render_svg(layer_codes, name, idx):
    U = 56           # taille touche px
    PAD = 24
    positions = {}
    for slot, code in enumerate(layer_codes):
        if slot in GAPS:
            continue
        positions[slot] = (slot_pos(slot), code)
    xs = [p[0] for (p, _) in positions.values()]
    ys = [p[1] for (p, _) in positions.values()]
    w = int((max(xs) - min(xs) + 1) * U + 2 * PAD)
    h = int((max(ys) - min(ys) + 1) * U + 2 * PAD + 34)
    minx, miny = min(xs), min(ys)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" font-family="ui-monospace,Menlo,monospace">',
        f'<rect width="{w}" height="{h}" rx="14" fill="#1b1d23"/>',
        f'<text x="{PAD}" y="26" fill="#e6e6e6" font-size="18" '
        f'font-weight="700">Layer {idx} — {esc(name)}</text>',
    ]
    for slot, ((x, y), code) in sorted(positions.items()):
        px = PAD + (x - minx) * U
        py = PAD + 34 + (y - miny) * U
        short, _ = decode(code)
        transparent = code in (0, 65535, 65534)
        fill = "#23262e" if transparent else "#2d3340"
        stroke = "#33373f" if transparent else "#4a5265"
        out.append(
            f'<rect x="{px:.1f}" y="{py:.1f}" width="{U-6}" height="{U-6}" '
            f'rx="7" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>'
        )
        if short:
            fs = 15 if len(short) <= 3 else (12 if len(short) <= 6 else 9)
            out.append(
                f'<text x="{px + (U-6)/2:.1f}" y="{py + (U-6)/2 + fs/3:.1f}" '
                f'text-anchor="middle" fill="#dfe4ee" font-size="{fs}">'
                f'{esc(short)}</text>'
            )
    out.append("</svg>")
    return "\n".join(out)


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def yaml_scalar(s):
    """JSON est du YAML valide pour un scalaire → quoting sûr."""
    return json.dumps(s, ensure_ascii=False)


def used(layer_codes):
    return any(c not in (0, 65535, 65534) for c in layer_codes)


def main():
    files = glob.glob(BACKUP_GLOB)
    if not files:
        sys.exit(f"Aucun backup trouvé via {BACKUP_GLOB}")
    latest = max(files, key=lambda f: os.path.basename(f))  # nom = horodatage
    data = json.load(open(latest))
    codes = next(
        item["data"].split()
        for item in data["backup"] if item["command"] == "keymap.custom"
    )
    codes = list(map(int, codes))
    layers = [codes[i * 80:(i + 1) * 80] for i in range(10)]
    names = {l["id"]: l["name"] for l in data.get("neuron", {}).get("layers", [])}

    # 1. JSON brut (source de vérité pour re-flasher)
    with open(os.path.join(REPO, "defy.json"), "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # 2. YAML lisible
    ydir = ["# Généré par sync.py — ne pas éditer à la main.",
            f"source: {yaml_scalar(os.path.basename(latest))}",
            f"neuronID: {yaml_scalar(data.get('neuronID',''))}",
            "layers:"]
    rendered = []
    os.makedirs(os.path.join(REPO, "layouts"), exist_ok=True)
    for idx, lc in enumerate(layers):
        if not used(lc):
            continue
        nm = names.get(idx, f"layer{idx}")
        ydir.append(f"  - index: {idx}")
        ydir.append(f"    name: {yaml_scalar(nm)}")
        ydir.append("    keys:")
        for slot, code in enumerate(lc):
            if slot in GAPS:
                continue
            _, desc = decode(code)
            ydir.append(f"      - {{slot: {slot}, code: {code}, key: {yaml_scalar(desc)}}}")
        svg = render_svg(lc, nm, idx)
        slug = re.sub(r"[^a-z0-9]+", "-", nm.lower()).strip("-") or f"layer{idx}"
        path = f"layouts/layer-{idx}-{slug}.svg"
        with open(os.path.join(REPO, path), "w") as f:
            f.write(svg)
        rendered.append((idx, nm, path))
    with open(os.path.join(REPO, "layers.yaml"), "w") as f:
        f.write("\n".join(ydir) + "\n")

    # 3. README
    rd = ["# Dygma Defy — config", "",
          f"Dernier backup : `{os.path.basename(latest)}`  ",
          f"neuronID : `{data.get('neuronID','')}`", "",
          "Généré depuis les backups Bazecor par [`sync.py`](./sync.py).",
          "Source de vérité re-flashable : [`defy.json`](./defy.json) · "
          "transcription : [`layers.yaml`](./layers.yaml).", "",
          "## Layers", ""]
    for idx, nm, path in rendered:
        rd += [f"### Layer {idx} — {nm}", "", f"![layer {idx}]({path})", ""]
    with open(os.path.join(REPO, "README.md"), "w") as f:
        f.write("\n".join(rd) + "\n")

    print(f"OK: {os.path.basename(latest)} → {len(rendered)} layer(s) rendus")
    git_commit(os.path.basename(latest))


def git(*args):
    return subprocess.run(["git", "-C", REPO, *args],
                          capture_output=True, text=True)


def git_commit(tag):
    if not os.path.isdir(os.path.join(REPO, ".git")):
        git("init", "-q")
    git("add", "-A")
    if not git("diff", "--cached", "--quiet").returncode:
        print("Rien à committer.")
        return
    git("commit", "-q", "-m", f"defy: sync layout {tag}")
    print("Commit créé.")
    if git("remote").stdout.strip():
        r = git("push")
        print("Push OK." if r.returncode == 0 else f"Push échoué:\n{r.stderr}")
    else:
        print("Pas de remote — ajoute-le puis push :\n"
              "  git -C %s remote add origin <url> && git -C %s push -u origin HEAD"
              % (REPO, REPO))


if __name__ == "__main__":
    main()
