#!/usr/bin/env python3
"""Reverse of sync.py: rebuild a re-flashable Bazecor JSON from layers.yaml.

layers.yaml carries the raw `code` of every slot, so we just reassemble the
keymap.custom string. Everything the YAML doesn't cover (GAP slots, unused
layers, superkeys, colormap, LED, settings) is kept verbatim from a base
defy.json — so the round-trip is lossless."""

import json
import os
import re
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(REPO, "defy.json")
YAML = os.path.join(REPO, "layers.yaml")
OUT = os.path.join(REPO, "restored-Defy.json")


def yaml_codes(path):
    """Parse layers.yaml → {(layer, slot): code}."""
    codes, layer = {}, None
    for line in open(path):
        m = re.match(r"\s+- index: (\d+)", line)
        if m:
            layer = int(m.group(1))
            continue
        m = re.search(r"slot: (\d+), code: (\d+)", line)
        if m and layer is not None:
            codes[(layer, int(m.group(1)))] = int(m.group(2))
    return codes


def rebuild(base_json, codes):
    """Return a copy of base_json with keymap.custom patched from `codes`."""
    data = json.loads(json.dumps(base_json))          # deep copy
    item = next(i for i in data["backup"] if i["command"] == "keymap.custom")
    km = list(map(int, item["data"].split()))
    for (layer, slot), code in codes.items():
        km[layer * 80 + slot] = code                   # GAPs/unused stay as-is
    item["data"] = " ".join(map(str, km))
    return data


def check():
    """Restoring the repo's own YAML onto its base must reproduce the keymap."""
    base = json.load(open(BASE))
    orig = next(i for i in base["backup"] if i["command"] == "keymap.custom")["data"]
    got = next(i for i in rebuild(base, yaml_codes(YAML))["backup"]
               if i["command"] == "keymap.custom")["data"]
    assert got == orig, "round-trip mismatch — YAML and defy.json disagree"
    print("check OK: layers.yaml round-trips to defy.json's keymap")


def main():
    if "--check" in sys.argv:
        return check()
    out = rebuild(json.load(open(BASE)), yaml_codes(YAML))
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"OK: {os.path.basename(YAML)} → {os.path.basename(OUT)} (flashable)")


if __name__ == "__main__":
    main()
