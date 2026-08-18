#!/usr/bin/env python3
"""
gds_to_rtl.py -- one pass from a stripped GDSII layout to the string the chip prints.

    python3 GDS-to-RTL/gds_to_rtl.py                  warm-up validation, then the puzzle
    python3 GDS-to-RTL/gds_to_rtl.py --only warmup
    python3 GDS-to-RTL/gds_to_rtl.py --only puzzle
    python3 GDS-to-RTL/gds_to_rtl.py --no-iverilog    skip the two simulator cross-checks

Inputs are only the files Jane Street shipped, in puzzle/ and warmup/, plus the
SkyWater sky130 PDK in pdk/. Everything in puzzle-solution/ and warmup-solution/
is regenerated from scratch.

Order of work:

  warm-up   inventory -> extract from polygons -> prove exact against the golden
            DEF and netlist -> simulate against the golden netlist -> solve it
            from the extracted gates with SAT

  puzzle    inventory -> extract from polygons -> replay the recorded silicon
            waveform -> recover the register structure -> falsify the first
            hypothesis -> read the region map out of the gates by probing ->
            solve the gates with SAT and prove the key unique -> corroborate
            with an independent constraint solve -> emit behavioural RTL and
            prove it cycle-equivalent -> read the answer off O[7:0]

Everything that needs to simulate the recovered gates uses the bit-parallel
two-valued simulator in class Gates: one Python int per net, one bit per trial,
so 121 probe runs or 540 grids cost the same as one. iverilog is used twice only,
as an independent second opinion.
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures
import contextlib
import json
import math
import os
import re
import subprocess
import sys
import time

import gdstk
import numpy as np
import shapely
from shapely.geometry import Point, Polygon
from shapely.strtree import STRtree

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

LIB = os.path.join(ROOT, "pdk", "sky130_fd_sc_hd__tt_025C_1v80.lib")
LEF = os.path.join(ROOT, "pdk", "sky130_fd_sc_hd_merged.lef")
PUZZLE_GDS = os.path.join(ROOT, "puzzle", "puzzle.gds")
PUZZLE_VCD = os.path.join(ROOT, "puzzle", "example_inputs.vcd")
WARMUP_GDS = os.path.join(ROOT, "warmup", "04_final.gds")
WARMUP_NET = os.path.join(ROOT, "warmup", "01_netlist.v")
WARMUP_DEF = os.path.join(ROOT, "warmup", "03_post_place_and_route.def")
POUT = os.path.join(ROOT, "puzzle-solution")
WOUT = os.path.join(ROOT, "warmup-solution")

N = 11
FRAME = N * N
STARS = 2

CONDUCTOR = [67, 68, 69, 70, 71, 72]
LNAME = {67: "li1", 68: "met1", 69: "met2", 70: "met3", 71: "met4", 72: "met5"}
LEF_LAYER = {v: k for k, v in LNAME.items()}
CUTNAME = {67: "mcon", 68: "via", 69: "via2", 70: "via3", 71: "via4"}
KNOWN_LAYER = {
    (78, 44): "hvtp", (81, 4): "areaid.standardc", (93, 44): "nsdm",
    (94, 20): "psdm", (95, 20): "npc", (235, 4): "prBoundary",
}
for _l, _n in ((64, "nwell"), (65, "diff"), (66, "poly"), (67, "li1"),
               (68, "met1"), (69, "met2"), (70, "met3"), (71, "met4"),
               (72, "met5")):
    for _d, _s in ((20, ""), (16, ".pin"), (5, ".label")):
        KNOWN_LAYER[(_l, _d)] = _n + _s
for _l, _n in ((65, "tap"), (66, "licon1"), (67, "mcon"), (68, "via"),
               (69, "via2"), (70, "via3"), (71, "via4")):
    KNOWN_LAYER[(_l, 44)] = _n
OUTPUT_PINS = {"X", "Y", "Q", "Q_N", "HI", "LO"}
POWER_PINS = {"VPWR", "VGND", "VPB", "VNB"}
PHYS_PREFIX = ("decap", "fill", "tapvpwrvgnd", "tap_")
GAP = 0.06
ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
SAT_BACKEND = "Cadical300"
SHARDS = max(1, min(16, os.cpu_count() or 1))


# ---------------------------------------------------------------------------
# logging
# ---------------------------------------------------------------------------

class Tee:
    """Send everything the pipeline prints to the terminal and to GDS-to-RTL/run.log."""

    def __init__(self, path):
        self.f = open(path, "w")

    def write(self, s):
        sys.__stdout__.write(s)
        self.f.write(s)

    def flush(self):
        sys.__stdout__.flush()
        self.f.flush()


_T0 = time.time()


@contextlib.contextmanager
def stage(tag, title):
    t = time.time()
    print(f"\n{tag}  {title}")
    yield
    print(f"    [{time.time() - t:.2f}s]")


def say(*a):
    print("    " + " ".join(str(x) for x in a))


def write(path, text):
    with open(path, "w") as f:
        f.write(text if text.endswith("\n") else text + "\n")
    return path


# ---------------------------------------------------------------------------
# boolean expressions, as the Liberty file writes them
# ---------------------------------------------------------------------------

def parse_bool(expr, resolve):
    """Liberty boolean string -> AST. Leaves come back from resolve(name).

    Precedence, tightest first: postfix ' , prefix ! , ^ , & (or * or a bare
    space) , | (or +). Nodes are tuples: ('&',a,b) ('|',a,b) ('^',a,b) ('!',a)
    ('c',0|1) or whatever resolve() returns for an identifier.
    """
    toks = re.findall(r"[A-Za-z_][A-Za-z0-9_\[\]]*|[()!'^&|*+]|\S", expr)
    pos = [0]

    def peek():
        return toks[pos[0]] if pos[0] < len(toks) else None

    def take():
        t = peek()
        pos[0] += 1
        return t

    def primary():
        t = take()
        if t == "(":
            e = or_expr()
            if peek() == ")":
                take()
            return e
        if t in ("0", "1"):
            return ("c", int(t))
        return resolve(t)

    def postfix():
        e = primary()
        while peek() == "'":
            take()
            e = ("!", e)
        return e

    def not_expr():
        if peek() == "!":
            take()
            return ("!", not_expr())
        return postfix()

    def xor_expr():
        e = not_expr()
        while peek() == "^":
            take()
            e = ("^", e, not_expr())
        return e

    def and_expr():
        e = xor_expr()
        while True:
            t = peek()
            if t in ("&", "*"):
                take()
                e = ("&", e, xor_expr())
            elif t is not None and (t == "(" or re.match(r"^[A-Za-z_]", t) or t == "!"):
                e = ("&", e, xor_expr())
            else:
                return e

    def or_expr():
        e = and_expr()
        while peek() in ("|", "+"):
            take()
            e = ("|", e, and_expr())
        return e

    return or_expr()


def ast_py(node):
    """AST -> a Python expression over v[] and the lane mask M."""
    k = node[0]
    if k == "n":
        return f"v[{node[1]}]"
    if k == "c":
        return "M" if node[1] else "0"
    if k == "!":
        return f"(M^{ast_py(node[1])})"
    op = {"&": "&", "|": "|", "^": "^"}[k]
    return f"({ast_py(node[1])}{op}{ast_py(node[2])})"


def ast_nets(node, out):
    if node[0] == "n":
        out.add(node[1])
    elif node[0] == "!":
        ast_nets(node[1], out)
    elif node[0] in ("&", "|", "^"):
        ast_nets(node[1], out)
        ast_nets(node[2], out)
    return out


# ---------------------------------------------------------------------------
# the PDK: what every standard cell does
# ---------------------------------------------------------------------------

def liberty(path):
    """Parse the sky130 Liberty into {cell: {'dir':{pin:in|out}, 'func':{pin:str},
    'ff': {'next_state','clocked_on','clear','preset'} or None}}.

    Combinational cells state a boolean 'function' per output pin. Sequential
    cells carry an ff() group naming the internal state pair, its next_state,
    its clock, and the level-sensitive clear/preset expressions; their output
    pins then simply 'function : IQ' or 'IQ_N'. Both come from the same file the
    synthesiser read, so no cell truth table is ever written out by hand here.
    """
    text = open(path).read()
    out = {}
    for chunk in re.split(r"\n    cell \(", text)[1:]:
        name = re.match(r'\s*"?([\w]+)"?\s*\)', chunk)
        if not name:
            continue
        pins, funcs = {}, {}
        parts = re.split(r"\n        pin \(", chunk)
        for pb in parts[1:]:
            pn = re.match(r'\s*"?([\w\[\]]+)"?\s*\)', pb)
            if not pn:
                continue
            dm = re.search(r'\n\s+direction\s*:\s*"?(\w+)"?', pb)
            fm = re.search(r'\n\s+function\s*:\s*"([^"]*)"', pb)
            pins[pn.group(1)] = dm.group(1) if dm else "?"
            if fm:
                funcs[pn.group(1)] = fm.group(1)
        ffm = re.search(r'\n\s+ff \(\s*"?(\w+)"?\s*,\s*"?(\w+)"?\s*\)\s*\{([^}]*)\}',
                        parts[0])
        ff = None
        if ffm:
            fb = ffm.group(3)
            get = lambda k: (re.search(k + r'\s*:\s*"([^"]*)"', fb) or [None, None])[1]
            ff = {"iq": ffm.group(1), "iqn": ffm.group(2),
                  "next_state": get("next_state"), "clocked_on": get("clocked_on"),
                  "clear": get("clear"), "preset": get("preset")}
        out[name.group(1)] = {"dir": pins, "func": funcs, "ff": ff}
    return out


def emit_models(lib, wanted, path):
    """Verilog simulation models for exactly the cells this design uses.

    Only iverilog needs these: the Python simulator evaluates the Liberty
    directly. Generated, never hand written.
    """
    body = []
    for cname in sorted(wanted):
        c = lib.get(cname)
        if c is None:
            body.append(f"module {cname} ();\nendmodule\n")
            continue
        sig = [p for p in c["dir"] if p not in POWER_PINS]
        lines = [f"module {cname} (" + ", ".join(sig) + ");"]
        for p in sig:
            lines.append(f"  {'input ' if c['dir'][p] == 'input' else 'output'} {p};")
        ff = c["ff"]
        if ff:
            init = "1'b1" if (ff["preset"] and not ff["clear"]) else "1'b0"
            edge = [f"posedge {ff['clocked_on']}"]
            act = []
            if ff["clear"]:
                net = ff["clear"].lstrip("!")
                edge.append(f"negedge {net}")
                act.append(f"    if (!{net}) q <= 1'b0;")
            if ff["preset"]:
                net = ff["preset"].lstrip("!")
                edge.append(f"negedge {net}")
                act.append(f"    {'else ' if act else ''}if (!{net}) q <= 1'b1;")
            act.append(f"    {'else ' if act else ''}q <= {ff['next_state']};")
            lines.append(f"  reg q = {init};")
            lines.append("  always @(" + " or ".join(edge) + ")")
            lines += act
            for p in sig:
                f = c["func"].get(p)
                if f == ff["iq"]:
                    lines.append(f"  assign {p} = q;")
                elif f == ff["iqn"]:
                    lines.append(f"  assign {p} = ~q;")
        else:
            for p in sig:
                if c["dir"][p] == "output" and p in c["func"]:
                    e = re.sub(r"\bVGND\b", "1'b0",
                               re.sub(r"\bVPWR\b", "1'b1", c["func"][p]))
                    lines.append(f"  assign {p} = {e.replace('!', '~')};")
        lines.append("endmodule\n")
        body.append("\n".join(lines))
    return write(path, f"// sky130 cell models generated from {os.path.basename(LIB)}\n"
                       f"// {len(wanted)} cells. Source of truth is the Liberty "
                       f"'function' / 'ff' data, not hand-written tables.\n\n"
                 + "\n".join(body))


# ---------------------------------------------------------------------------
# stage 1: what is in the GDS
# ---------------------------------------------------------------------------

def orient(rot_deg, mirror):
    key = (int(round(rot_deg)) % 360, bool(mirror))
    return {(0, False): "N", (180, False): "S", (180, True): "FN", (0, True): "FS",
            (90, False): "W", (270, False): "E", (90, True): "FW",
            (270, True): "FE"}.get(key, f"R{key[0]}{'M' if mirror else ''}")


def inventory(gds_path, out_path):
    """Bill of materials for a GDSII file, written to out_path.

    A GDS holds polygons tagged (layer, datatype) plus placements of other
    structures. It has no notion of a wire, a gate, a pin or a connection. The
    one thing this flow did not strip is the structure names, and those are the
    foundry cell names, so the placement list comes back for free.
    """
    lib = gdstk.read_gds(gds_path)
    top = lib.top_level()[0]
    bb = top.bounding_box()
    L = [f"GDS INVENTORY: {os.path.relpath(gds_path, ROOT)}", "=" * 70, "",
         f"library            {lib.name}",
         f"units              {lib.unit} m, precision {lib.precision} m",
         f"structures in file {len(lib.cells)}",
         f"top structure      {top.name}",
         f"bounding box       ({bb[0][0]:.2f}, {bb[0][1]:.2f}) .. "
         f"({bb[1][0]:.2f}, {bb[1][1]:.2f}) um",
         f"                   {(bb[1][0]-bb[0][0]):.2f} x "
         f"{(bb[1][1]-bb[0][1]):.2f} um"
         + ("   <- extends below y = 0, so something is drawn off the die"
            if bb[0][1] < 0 else ""),
         ""]

    kinds = collections.Counter()
    rows = []
    for ref in top.references:
        nm = ref.cell.name
        short = nm.split("__")[-1]
        if nm.startswith("VIA_"):
            k = "via"
        elif not nm.startswith("sky130_fd_sc_hd__"):
            k = "not a standard cell"
        elif short.startswith(PHYS_PREFIX):
            k = "physical only"
        elif short.startswith("diode"):
            k = "antenna diode"
        else:
            k = "logic"
            rows.append((nm, ref.origin[0], ref.origin[1],
                         orient(math.degrees(ref.rotation), ref.x_reflection)))
        kinds[(k, nm)] += 1

    tot = collections.Counter()
    for (k, nm), c in kinds.items():
        tot[k] += c
    L += ["PLACEMENTS", "-" * 70,
          f"  total {sum(tot.values())}"]
    for k in ("logic", "via", "physical only", "antenna diode", "not a standard cell"):
        if tot[k]:
            L.append(f"  {k:22s} {tot[k]:6d}")
    L.append("")
    L.append(f"logic cell types: {len({nm for (k, nm) in kinds if k == 'logic'})}")
    for (k, nm), c in sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0][1])):
        if k == "logic":
            L.append(f"  {c:5d} x {nm}")
    L.append("")
    for k in ("via", "physical only", "antenna diode", "not a standard cell"):
        got = sorted(((c, nm) for (kk, nm), c in kinds.items() if kk == k), reverse=True)
        if got:
            L.append(f"{k} structures:")
            for c, nm in got:
                L.append(f"  {c:5d} x {nm}")
            L.append("")

    L += ["SURVIVING TEXT LABELS IN THE TOP CELL  (these are the I/O ports)",
          "-" * 70]
    for lab in top.labels:
        L.append(f"  {lab.text!r:12s} on layer {lab.layer}/{lab.texttype}"
                 f"  at ({lab.origin[0]:.2f}, {lab.origin[1]:.2f})")
    L.append("")

    pinlab = collections.Counter()
    example = None
    for c in {r.cell.name: r.cell for r in top.references}.values():
        if not c.name.startswith("sky130_fd_sc_hd__"):
            continue
        for lab in c.labels:
            pinlab[lab.text] += 1
        if example is None and c.labels:
            example = (c.name, [(l.text, f"{l.layer}/{l.texttype}") for l in c.labels])
    L += [f"PIN LABELS INSIDE THE CELL DEFINITIONS: {sum(pinlab.values())} labels, "
          f"{len(pinlab)} distinct names", "-" * 70,
          "  " + " ".join(sorted(pinlab)), ""]
    if example:
        L.append(f"  example, {example[0]}: {example[1]}")
        L.append("")

    hist = collections.Counter()
    for p in top.polygons:
        hist[(p.layer, p.datatype)] += 1
    for p in top.paths:
        hist[(p.layers[0], p.datatypes[0])] += 1
    L += ["GEOMETRY DRAWN DIRECTLY IN THE TOP CELL  (inter-cell routing + power)",
          "-" * 70]
    for k in sorted(hist):
        nm = KNOWN_LAYER.get(k, "")
        tag = "  <- conductor, extracted" if (k[1] == 20 and k[0] in CONDUCTOR) else ""
        L.append(f"  {k[0]:3d}/{k[1]:<3d} {nm:18s} {hist[k]:6d} shapes{tag}")
    L.append("")

    whole = collections.Counter()
    for c in lib.cells:
        for p in c.polygons:
            whole[(p.layer, p.datatype)] += 1
    L += ["EVERY LAYER IN THE FILE, CELL INTERIORS INCLUDED", "-" * 70]
    for k in sorted(whole):
        nm = KNOWN_LAYER.get(k, "not a sky130 mask layer")
        L.append(f"  {k[0]:3d}/{k[1]:<3d} {nm:24s} {whole[k]:7d} polygons")
    L.append("")

    L += [f"EVERY LOGIC PLACEMENT ({len(rows)} rows): cell, x_um, y_um, orientation",
          "-" * 70]
    for nm, x, y, o in sorted(rows, key=lambda r: (r[2], r[1])):
        L.append(f"  {nm:34s} {x:9.3f} {y:9.3f}  {o}")

    write(out_path, "\n".join(L))
    return {"top": top.name, "bbox": bb, "structures": len(lib.cells),
            "placements": sum(tot.values()), "logic": tot["logic"], "via": tot["via"],
            "phys": tot["physical only"], "diode": tot["antenna diode"],
            "odd": tot["not a standard cell"],
            "types": len({nm for (k, nm) in kinds if k == "logic"}),
            "labels": [l.text for l in top.labels],
            "toplayers": hist, "alllayers": whole, "pinlabels": len(pinlab)}


# ---------------------------------------------------------------------------
# stage 2: which pins are wired together
# ---------------------------------------------------------------------------

def lef_pin_rects(path):
    """Complete pin landing geometry per macro: {macro: {pin: [(layer, Polygon)]}}.

    Tagging pins from the GDS text labels alone is the first silent trap in this
    whole exercise: a label marks exactly one polygon, while a real pin is often
    several polygons in different places in the cell, any of which the router may
    land on. LEF PIN/PORT/RECT is the authoritative list, so take all of them.
    """
    macros, m, p, lay, flat = {}, None, None, None, []
    for line in open(path):
        w = line.split()
        if not w:
            continue
        k = w[0]
        if k == "MACRO":
            m, p = w[1], None
            macros[m] = {}
        elif m is None:
            continue
        elif k == "PIN":
            p = w[1]
            macros[m].setdefault(p, [])
        elif k == "OBS":
            p = None
        elif k == "END" and len(w) > 1:
            if w[1] == p:
                p = None
            elif w[1] == m:
                m = None
        elif k == "LAYER" and p is not None:
            lay = LEF_LAYER.get(w[1])
        elif k == "RECT" and p is not None and lay is not None:
            macros[m][p].append((lay, tuple(map(float, w[1:5]))))
            flat.append((macros[m][p], len(macros[m][p]) - 1))
    boxes = shapely.box(*np.array([slot[i][1] for slot, i in flat]).T)
    for (slot, i), poly in zip(flat, boxes):
        slot[i] = (slot[i][0], poly)
    return macros


def _affine(ref):
    """shapely coefficients for a gdstk reference: mirror in X, rotate, translate."""
    s = -1.0 if ref.x_reflection else 1.0
    c, si = math.cos(ref.rotation), math.sin(ref.rotation)
    return [c, -s * si, si, s * c, ref.origin[0], ref.origin[1]]


def _shapes(cell, layer, datatype):
    """Every polygon a cell draws on one layer, built in one vectorised call."""
    pts = [p.points for p in cell.polygons
           if p.layer == layer and p.datatype == datatype]
    for path in cell.paths:
        if path.layers[0] == layer and path.datatypes[0] == datatype:
            pts += [q.points for q in path.to_polygons()]
    if not pts:
        return []
    idx = np.repeat(np.arange(len(pts)), [len(q) for q in pts])
    return list(shapely.polygons(
        shapely.linearrings(np.concatenate(pts), indices=idx)))


def _rep_xy(poly):
    """A point guaranteed to lie inside a polygon, as a plain (x, y) pair.

    An affine map sends interior points to interior points, so this is taken
    once per cell definition and then moved by the numpy transform below, rather
    than transforming the polygon and asking shapely again at every placement.
    """
    p = poly.representative_point()
    return (p.x, p.y)


def _xform_polys(polys, mats):
    """Affine-transform many polygons in one numpy pass instead of one call each."""
    if not polys:
        return []
    arr = shapely.transform(np.asarray(polys, dtype=object), lambda c: c)
    co = shapely.get_coordinates(arr)
    M = np.repeat(np.asarray(mats, dtype=float),
                  shapely.get_num_coordinates(arr), axis=0)
    x, y = co[:, 0], co[:, 1]
    shapely.set_coordinates(arr, np.column_stack(
        (M[:, 0] * x + M[:, 1] * y + M[:, 4],
         M[:, 2] * x + M[:, 3] * y + M[:, 5])))
    return list(arr)


def _xform_pts(xy, mats):
    """The same transform for bare (x, y) marks, pure numpy."""
    if not xy:
        return np.empty((0, 2))
    P, M = np.asarray(xy, dtype=float), np.asarray(mats, dtype=float)
    return np.column_stack((M[:, 0] * P[:, 0] + M[:, 1] * P[:, 1] + M[:, 4],
                            M[:, 2] * P[:, 0] + M[:, 3] * P[:, 1] + M[:, 5]))


def extract(gds_path, outdir, name):
    """Recover a gate netlist from raw geometry. Returns (path, stats).

    The whole of it is three ideas:

      1. flatten every conductor polygon to top-level coordinates, then join any
         two polygons on the same layer that overlap, so each group is one
         contiguous piece of metal;
      2. every via cut joins the metal below it to the metal above it;
      3. union-find over both, then look up which group covers each cell pin.

    Same-layer overlap means connected. Different layers mean nothing without a
    cut. That is the entire electrical content of a GDS file.

    Note on step 1. The obvious way to write it is to hand every polygon on a
    layer to shapely's unary_union and let it merge them into islands, but that
    computes an exact merged outline that nothing downstream ever reads. What is
    actually wanted is the connected components of the relation "these two
    polygons touch", and running that relation directly over the raw polygons
    through one STRtree query per layer gives the identical partition, because
    the distance from a point to a union of shapes is the smallest of the
    distances to its members. Measured on puzzle.gds the two agree island for
    island on every layer, and the direct version is about eleven times faster.
    """
    lib = gdstk.read_gds(gds_path)
    top = lib.top_level()[0]
    lefpins = lef_pin_rects(LEF)

    celltypes, viatypes = {}, {}
    for c in {r.cell.name: r.cell for r in top.references}.values():
        if c.name.startswith("VIA_"):
            pads = {l: ps for l in CONDUCTOR for ps in [_shapes(c, l, 20)] if ps}
            viatypes[c.name] = {"pads": pads,
                                "mark": {l: _rep_xy(ps[0]) for l, ps in pads.items()}}
            continue
        short = c.name.split("__")[-1]
        if not c.name.startswith("sky130") or short.startswith(PHYS_PREFIX):
            celltypes[c.name] = None
            continue
        cond = {l: ps for l in CONDUCTOR for ps in [_shapes(c, l, 20)] if ps}
        pins = collections.defaultdict(list)
        for lab in c.labels:
            if (lab.layer, lab.texttype) == (67, 5) and lab.text not in POWER_PINS:
                pt = Point(lab.origin)
                pins[lab.text] += [(67, p) for p in cond.get(67, [])
                                   if p.buffer(0.005).intersects(pt)]
        for pname, rects in lefpins.get(c.name, {}).items():
            if pname not in POWER_PINS:
                pins[pname] += rects
        celltypes[c.name] = {
            "pins": {p: [(l, _rep_xy(q)) for l, q in v] for p, v in pins.items()},
            "cond": cond,
            "mcon": [_rep_xy(p) for p in _shapes(c, 67, 44)],
            "bridge": short.startswith("diode")}

    jobs = {l: ([], []) for l in CONDUCTOR}
    mxy, mmat = [], []
    pin_marks, via_marks, instances = [], [], []
    for ref in top.references:
        cname = ref.cell.name
        A = _affine(ref)
        if cname in viatypes:
            v = viatypes[cname]
            layers = sorted(v["pads"])
            grp = []
            for l in layers:
                jobs[l][0].extend(v["pads"][l])
                jobs[l][1].extend([A] * len(v["pads"][l]))
                grp.append((l, len(mxy)))
                mxy.append(v["mark"][l])
                mmat.append(A)
            via_marks.append((layers[0], grp))
            continue
        info = celltypes.get(cname)
        if info is None:
            continue
        for l, ps in info["cond"].items():
            jobs[l][0].extend(ps)
            jobs[l][1].extend([A] * len(ps))
        for xy in info["mcon"]:
            via_marks.append((67, [(67, len(mxy)), (68, len(mxy))]))
            mxy.append(xy)
            mmat.append(A)
        if not info["pins"]:
            continue
        idx = len(instances)
        instances.append({"idx": idx, "cell": cname, "bridge": info["bridge"],
                          "x": round(ref.origin[0], 4), "y": round(ref.origin[1], 4),
                          "rot": round(math.degrees(ref.rotation)) % 360,
                          "mirror": bool(ref.x_reflection)})
        for pname, marks in info["pins"].items():
            for lay, xy in marks:
                pin_marks.append((lay, len(mxy), idx, pname))
                mxy.append(xy)
                mmat.append(A)

    mark_pt = shapely.points(_xform_pts(mxy, mmat))

    metal, trees, base, stats = {}, {}, {}, []
    total = 0
    for l in CONDUCTOR:
        polys, mats = jobs[l]
        arr = np.asarray(_xform_polys(polys, mats)
                         + _shapes(top, l, 20) + _shapes(top, l, 16), dtype=object)
        metal[l], base[l] = arr, total
        trees[l] = STRtree(arr) if len(arr) else None
        total += len(arr)

    parent = list(range(total))

    def find(a):
        r = a
        while parent[r] != r:
            r = parent[r]
        while parent[a] != r:
            parent[a], a = r, parent[a]
        return r

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra == rb:
            return False
        parent[ra] = rb
        return True

    stitched = 0
    for l in CONDUCTOR:
        if trees[l] is None:
            continue
        hits = trees[l].query(metal[l], predicate="dwithin", distance=GAP)
        keep = hits[0] < hits[1]
        off = base[l]
        for i, j in zip((hits[0][keep] + off).tolist(),
                        (hits[1][keep] + off).tolist()):
            stitched += union(i, j)
    for l in CONDUCTOR:
        n = len(metal[l])
        stats.append((LNAME[l], n,
                      len({find(base[l] + i) for i in range(n)})))

    def locate(marks):
        """Bulk point-in-metal lookup, one STRtree query per layer."""
        out = {}
        bylayer = collections.defaultdict(list)
        for k, lay, mi in marks:
            bylayer[lay].append((k, mi))
        for lay, items in bylayer.items():
            if trees[lay] is None:
                continue
            pts = mark_pt[[mi for _, mi in items]]
            off = base[lay]
            for widen in (False, True):
                hits = trees[lay].query(shapely.buffer(pts, 0.01) if widen else pts,
                                        predicate="intersects")
                for a, b in zip(hits[0].tolist(), (hits[1] + off).tolist()):
                    out.setdefault((items[a][0], lay), b)
                if all((k, lay) in out for k, _ in items):
                    break
        return out

    vloc = locate([((vi, li), lay, mi) for vi, (_, grp) in enumerate(via_marks)
                   for li, (lay, mi) in enumerate(grp)])
    cuts = collections.Counter()
    bridged = collections.Counter()
    for vi, (lo, grp) in enumerate(via_marks):
        found = [vloc.get(((vi, li), lay)) for li, (lay, _) in enumerate(grp)]
        found = [c for c in found if c]
        key = CUTNAME.get(lo, f"L{lo}")
        cuts[key] += 1
        if len(found) >= 2:
            bridged[key] += 1
            for c in found[1:]:
                union(found[0], c)

    ploc = locate([((i, lay), lay, mi)
                   for i, (lay, mi, _, _) in enumerate(pin_marks)])
    by_pin = collections.defaultdict(list)
    unbound = 0
    for i, (lay, mi, idx, pname) in enumerate(pin_marks):
        c = ploc.get(((i, lay), lay))
        if c is None:
            unbound += 1
        else:
            by_pin[(idx, pname)].append(c)
    for clist in by_pin.values():
        for c in clist[1:]:
            union(clist[0], c)
    net_pins = collections.defaultdict(list)
    for key, clist in by_pin.items():
        net_pins[find(clist[0])].append(key)

    net_ports = collections.defaultdict(set)
    for lab in top.labels:
        if lab.texttype == 5 and lab.layer in (70, 71, 72):
            hits = trees[lab.layer].query(Point(lab.origin), predicate="intersects")
            if len(hits):
                net_ports[find(base[lab.layer] + int(hits[0]))].add(lab.text)

    nets = collections.defaultdict(lambda: {"pins": [], "ports": set()})
    for r, pl in net_pins.items():
        nets[find(r)]["pins"] += pl
    for r, po in net_ports.items():
        nets[find(r)]["ports"] |= po

    bridge_idx = {i["idx"] for i in instances if i["bridge"]}
    netlist = []
    for i, (root, d) in enumerate(sorted(nets.items(), key=lambda kv: str(kv[0]))):
        ports = d["ports"] - {"VPWR", "VGND"}
        pins = sorted({(ix, p) for ix, p in set(d["pins"]) if ix not in bridge_idx})
        if not pins and not ports:
            continue
        drivers = [(ix, p) for ix, p in pins if p in OUTPUT_PINS]
        netlist.append({"name": sorted(ports)[0] if ports else f"net_{i:03d}",
                        "ports": sorted(ports), "pins": pins, "drivers": drivers})
    bad = [n for n in netlist
           if len(n["drivers"]) + (1 if n["ports"] and not n["drivers"] else 0) != 1]

    pin2net = {}
    for n in netlist:
        for idx, p in n["pins"]:
            pin2net[(idx, p)] = n["name"]
    inputs = sorted({n["name"] for n in netlist if n["ports"] and not n["drivers"]})
    outputs = sorted({n["name"] for n in netlist if n["ports"] and n["drivers"]})
    internal = sorted({n["name"] for n in netlist if not n["ports"]})

    def decls(names, kw):
        buses, scalars = collections.defaultdict(list), []
        for nm in names:
            m = re.match(r"^(\w+)\[(\d+)\]$", nm)
            buses[m.group(1)].append(int(m.group(2))) if m else scalars.append(nm)
        heads, lines = [], []
        for s in sorted(scalars):
            heads.append(s)
            lines.append(f"  {kw} {s};")
        for b in sorted(buses):
            heads.append(b)
            lines.append(f"  {kw} [{max(buses[b])}:{min(buses[b])}] {b};")
        return heads, lines

    in_h, in_d = decls(inputs, "input ")
    out_h, out_d = decls(outputs, "output")
    wire_h, wire_d = decls(internal, "wire")
    undriven = [n["name"] for n in netlist if not n["drivers"] and not n["ports"]]

    vpath = os.path.join(outdir, name)
    with open(vpath, "w") as f:
        f.write(f"// Recovered from {os.path.relpath(gds_path, ROOT)} by geometry alone.\n"
                f"// No netlist, DEF or source file was read to produce this.\n"
                f"// {len(instances) - len(bridge_idx)} logic cells, {len(netlist)} nets, "
                f"{len(bad)} nets with a driver count other than one.\n")
        f.write(f"module {top.name}_extracted (" + ", ".join(in_h + out_h) + ");\n")
        for line in in_d + out_d + wire_d:
            f.write(line + "\n")
        for w in undriven:
            f.write(f"  assign {w} = 1'b0;   // no driver recovered\n")
        for inst in instances:
            if inst["bridge"]:
                continue
            conns = [(p, pin2net.get((inst["idx"], p)))
                     for p in sorted(celltypes[inst["cell"]]["pins"])]
            body = ", ".join(f".{p}({n})" for p, n in conns if n)
            f.write(f"  {inst['cell']} u{inst['idx']}_"
                    f"{inst['cell'].split('__')[-1]} ({body});\n")
        f.write("endmodule\n")

    return vpath, {"top": top.name, "layers": stats, "stitched": stitched,
                   "cuts": cuts, "bridged": bridged, "unbound": unbound,
                   "nets": len(netlist), "bad": bad, "undriven": undriven,
                   "logic": len(instances) - len(bridge_idx),
                   "diodes": len(bridge_idx), "inputs": inputs, "outputs": outputs,
                   "instances": instances,
                   "netjson": [{"name": n["name"], "ports": n["ports"],
                                "pins": n["pins"]} for n in netlist]}


# ---------------------------------------------------------------------------
# stage 3: the warm-up has an answer key, so use it
# ---------------------------------------------------------------------------

def golden_check(gds_path, def_path, golden_path, ex, out_path):
    """Prove the extraction exact against the warm-up's shipped DEF and netlist.

    Two netlists are the same circuit exactly when they cut the same set of pins
    into the same groups with the same ports attached. That is a statement about
    set partitions, so it can be checked while every instance is still called
    u17 and every net net_412.

    Matching a GDS placement to a DEF component needs the cell outline, and the
    second silent trap lives here: the nwell implant overhangs the cell, so a
    geometric bounding box is consistently too big and nothing matches. sky130
    draws the real abutment box on its own layer, 81/4.
    """
    lib = gdstk.read_gds(gds_path)
    box = {}
    for c in lib.cells:
        b = [p for p in c.polygons if (p.layer, p.datatype) == (81, 4)]
        if b:
            xs = [p[0] for p in b[0].points]
            ys = [p[1] for p in b[0].points]
            box[c.name] = ((min(xs), min(ys)), (max(xs), max(ys)))
        else:
            box[c.name] = c.bounding_box()

    txt = open(def_path).read()
    comps = {}
    m = re.search(r"^COMPONENTS \d+ ;\n(.*?)^END COMPONENTS", txt, re.S | re.M)
    for stmt in m.group(1).split(";"):
        mm = re.search(r"-\s+(\S+)\s+(\S+)\s+.*?(?:PLACED|FIXED)\s*\(\s*(-?\d+)\s+"
                       r"(-?\d+)\s*\)\s+(\w+)", stmt, re.S)
        if mm:
            comps[mm.group(1)] = (mm.group(2), int(mm.group(3)) / 1000.0,
                                  int(mm.group(4)) / 1000.0, mm.group(5))
    bykey = {(c, round(x, 3), round(y, 3)): n for n, (c, x, y, o) in comps.items()}

    idx2name = {}
    unmatched = []
    for inst in ex["instances"]:
        if inst["bridge"]:
            continue
        (x0, y0), (x1, y1) = box[inst["cell"]]
        pts = []
        for px, py in ((x0, y0), (x1, y1)):
            sy = -py if inst["mirror"] else py
            c, s = (math.cos(math.radians(inst["rot"])),
                    math.sin(math.radians(inst["rot"])))
            pts.append((inst["x"] + c * px - s * sy, inst["y"] + s * px + c * sy))
        key = (inst["cell"], round(min(p[0] for p in pts), 3),
               round(min(p[1] for p in pts), 3))
        nm = bykey.get(key)
        if nm is None:
            unmatched.append(inst)
        else:
            idx2name[inst["idx"]] = nm

    golden = {}
    for stmt in open(golden_path).read().split(";"):
        mm = re.search(r"(sky130_fd_sc_hd__\w+)\s+(\\?\S+)\s*\((.*)\)\s*$", stmt, re.S)
        if mm:
            golden[mm.group(2).lstrip("\\")] = {
                p: n.strip().lstrip("\\").rstrip()
                for p, n in re.findall(r"\.(\w+)\(\s*([^)]*?)\s*\)", mm.group(3))}
    gold = collections.defaultdict(set)
    for iname, pins in golden.items():
        for p, n in pins.items():
            if p not in POWER_PINS:
                gold[n].add((iname, p))

    ok, bad, mapping = 0, [], {}
    for net in ex["netjson"]:
        pins = {(idx2name[i], p) for i, p in net["pins"] if i in idx2name}
        if not pins:
            continue
        cands = {g for g, gp in gold.items() if pins & gp}
        exact = [g for g in cands if gold[g] == pins]
        ports = set(net["ports"])
        if len(cands) == 1 and exact:
            g = exact[0]
            isport = g if g in ("A", "B", "S", "clk", "en", "rst_n") else None
            if (isport is None) == (not ports) and (not ports or ports == {isport}):
                mapping[net["name"]] = g
                ok += 1
                continue
        bad.append((net["name"], sorted(pins), sorted(cands)))

    L = ["GOLDEN CROSS-CHECK OF THE WARM-UP EXTRACTION", "=" * 70, "",
         f"DEF components (decap and tap included) {len(comps)}",
         f"GDS logic placements                    "
         f"{len([i for i in ex['instances'] if not i['bridge']])}",
         f"placements matched to a DEF component   {len(idx2name)}"
         f"{'  ALL' if not unmatched else ''}", ""]
    for inst in unmatched:
        L.append(f"  UNMATCHED {inst}")
    L += [f"net partition vs {os.path.relpath(golden_path, ROOT)}",
          f"  exact matches  {ok}",
          f"  mismatches     {len(bad)}",
          f"  golden nets    {len(gold)}", ""]
    for nm, pins, cands in bad:
        L.append(f"  MISMATCH {nm}: {pins} vs {cands}")
    if not bad and ok == len(gold) and not unmatched:
        L += ["RESULT: the extracted netlist is the golden netlist. Identical "
              "partition of", "        pins into nets, identical port attachment. "
              "Names recovered from the DEF.", ""]
    L += ["NAMES RECOVERED (extracted index -> the name the flow deleted)", "-" * 70]
    for i in sorted(idx2name):
        cell = comps[idx2name[i]][0].split("__")[-1]
        L.append(f"  u{i:<4d} {cell:12s} {idx2name[i]}")
    write(out_path, "\n".join(L))
    return {"comps": len(comps), "matched": len(idx2name),
            "unmatched": len(unmatched), "ok": ok, "bad": len(bad),
            "gold": len(gold), "names": idx2name, "netmap": mapping}


# ---------------------------------------------------------------------------
# the netlist, and a fast simulator for it
# ---------------------------------------------------------------------------

def read_netlist(path):
    """Parse a flat structural sky130 netlist. Returns (top, ports, insts, assigns)."""
    txt = open(path).read()
    txt = re.sub(r"//[^\n]*", "", txt)
    top = re.search(r"\bmodule\s+(\w+)", txt).group(1)
    ports = {}
    for kind, rng, nm in re.findall(
            r"^\s*(input|output)\s*(\[\s*\d+\s*:\s*\d+\s*\])?\s*(\w+)\s*;", txt, re.M):
        if rng:
            hi, lo = (int(x) for x in re.findall(r"\d+", rng))
            for b in range(min(hi, lo), max(hi, lo) + 1):
                ports[f"{nm}[{b}]"] = kind
        else:
            ports[nm] = kind
    insts = []
    for cell, nm, body in re.findall(
            r"(sky130_fd_sc_hd__\w+)\s+(\w+)\s*\(([^;]*)\);", txt, re.S):
        insts.append((cell, nm, {p: v.strip()
                                 for p, v in re.findall(r"\.(\w+)\(([^)]*)\)", body)}))
    assigns = dict(re.findall(r"assign\s+([\w\[\]]+)\s*=\s*1'b([01])\s*;", txt))
    return top, ports, insts, assigns


class Gates:
    """Bit-parallel two-valued simulator for a flat sky130 gate netlist.

    Every net is one Python int; bit k of that int is the net's value in trial k.
    A NAND over 540 independent grids therefore costs exactly one machine AND and
    one XOR, so a 540-trial sweep costs the same as a single run. The gate
    functions come from the Liberty file, so nothing about cell behaviour is
    asserted here by hand.

    The same parsed cell functions are reused by cnf() to hand the netlist to a
    SAT solver, which keeps the simulated circuit and the solved circuit
    literally the same object.
    """

    def __init__(self, path, lib):
        self.top, self.ports, insts, assigns = read_netlist(path)
        self.lib = lib
        self.idx = {}
        self.names = []

        def nid(nm):
            if nm not in self.idx:
                self.idx[nm] = len(self.names)
                self.names.append(nm)
            return self.idx[nm]

        for nm in self.ports:
            nid(nm)
        for _, _, conns in insts:
            for v in conns.values():
                if v:
                    nid(v)

        self.comb = []
        self.flops = []
        self.cellof = {}
        self.instnets = {}
        for cell, nm, conns in insts:
            c = lib[cell]
            self.cellof[nm] = cell.split("__")[-1]
            self.instnets[nm] = conns
            resolve = lambda t: ("n", nid(conns[t])) if conns.get(t) else ("c", 0)
            ff = c["ff"]
            if ff:
                q = qn = None
                for p, f in c["func"].items():
                    if p in conns and conns[p]:
                        if f == ff["iq"]:
                            q = nid(conns[p])
                        elif f == ff["iqn"]:
                            qn = nid(conns[p])
                self.flops.append({
                    "inst": nm, "q": q, "qn": qn,
                    "d": parse_bool(ff["next_state"], resolve),
                    "clk": conns.get(ff["clocked_on"]),
                    "clr": parse_bool(ff["clear"], resolve) if ff["clear"] else None,
                    "pre": parse_bool(ff["preset"], resolve) if ff["preset"] else None,
                    "init": 1 if (ff["preset"] and not ff["clear"]) else 0})
                continue
            for p, f in c["func"].items():
                if c["dir"].get(p) != "output" or not conns.get(p):
                    continue
                self.comb.append((nid(conns[p]),
                                  parse_bool(re.sub(r"\bVPWR\b", "1",
                                                    re.sub(r"\bVGND\b", "0", f)),
                                             resolve)))
        for nm, val in assigns.items():
            self.comb.append((nid(nm), ("c", int(val))))

        self.state = sorted({f[k] for f in self.flops for k in ("q", "qn")
                             if f[k] is not None})
        self.inputs = [n for n, k in self.ports.items() if k == "input"]
        self.outputs = [n for n, k in self.ports.items() if k == "output"]
        driven = {o for o, _ in self.comb} | set(self.state)
        self.order = self._levelize(driven)
        self._codegen()

    def _levelize(self, driven):
        combof = {o: a for o, a in self.comb}
        deps = {o: {d for d in ast_nets(a, set()) if d in combof}
                for o, a in self.comb}
        ready = collections.deque(o for o, d in deps.items() if not d)
        users = collections.defaultdict(list)
        for o, d in deps.items():
            for x in d:
                users[x].append(o)
        left = {o: len(d) for o, d in deps.items()}
        order = []
        while ready:
            o = ready.popleft()
            order.append(o)
            for u in users[o]:
                left[u] -= 1
                if not left[u]:
                    ready.append(u)
        if len(order) != len(self.comb):
            raise SystemExit("combinational loop in the extracted netlist")
        return order

    def _codegen(self):
        combof = {o: a for o, a in self.comb}
        src = ["def _comb(v, M):"]
        for o in self.order:
            src.append(f"    v[{o}] = {ast_py(combof[o])}")
        src.append("    return v")
        src.append("def _edge(v, M):")
        for i, f in enumerate(self.flops):
            d = ast_py(f["d"])
            clr = ast_py(f["clr"]) if f["clr"] else "0"
            pre = ast_py(f["pre"]) if f["pre"] else "0"
            src.append(f"    q{i} = (M^({clr}))&(({pre})|({d}))")
        for i, f in enumerate(self.flops):
            if f["q"] is not None:
                src.append(f"    v[{f['q']}] = q{i}")
            if f["qn"] is not None:
                src.append(f"    v[{f['qn']}] = M^q{i}")
        src.append("    return v")
        ns = {}
        exec(compile("\n".join(src), "<gates>", "exec"), ns)
        self._comb, self._edge = ns["_comb"], ns["_edge"]
        self.lines = len(src)

    def clock_tree(self):
        """Confirm every flop clock traces back to the same primary input."""
        combof = {o: a for o, a in self.comb}
        roots = set()
        for f in self.flops:
            seen, stack = set(), [self.idx[f["clk"]]]
            while stack:
                n = stack.pop()
                if n in seen:
                    continue
                seen.add(n)
                if n in combof:
                    stack += list(ast_nets(combof[n], set()))
                else:
                    roots.add(self.names[n])
        return roots

    def reset(self, lanes, xinit=0):
        """Fresh state vector: the value every flop holds after a reset pulse."""
        self.M = (1 << lanes) - 1
        self.lanes = lanes
        v = [0] * len(self.names)
        for f in self.flops:
            q = self.M if f["init"] else (self.M if (f["clr"] is None and
                                                    f["pre"] is None and xinit) else 0)
            if f["q"] is not None:
                v[f["q"]] = q
            if f["qn"] is not None:
                v[f["qn"]] = self.M ^ q
        self.v = v
        return v

    def poke(self, **kw):
        for nm, val in kw.items():
            self.v[self.idx[nm]] = val

    def edge(self):
        """One rising clock edge: settle, capture, settle again."""
        self._comb(self.v, self.M)
        self._edge(self.v, self.M)
        self._comb(self.v, self.M)

    def get(self, nm):
        return self.v[self.idx[nm]]

    def bus(self, base, width):
        return [self.v[self.idx[f"{base}[{b}]"]] for b in range(width)]

    def byte(self, base, lane, width=8):
        bits = self.bus(base, width)
        return sum((1 << b) for b in range(width) if (bits[b] >> lane) & 1)


# ---------------------------------------------------------------------------
# driving the recovered chip
# ---------------------------------------------------------------------------

def run_grids(g, grids, tail=0, xinit=0, watch=(), midwatch=()):
    """Shift one grid per lane into the recovered chip and report what it says.

    grids is a list of 121-character strings, one per trial. Trial k becomes bit
    k of every net, so a hundred grids cost one pass.

    Returns (success bitmask, [O bus per tail cycle], {watched net: end-of-frame
    bitmask}, {watched net: bitmask of lanes where it was high in the cycle that
    lane's own cell was fed}). The last one identifies state that is cleared
    again before the frame ends.
    """
    lanes = [sum(1 << k for k, gr in enumerate(grids) if gr[i] == "1")
             for i in range(FRAME)]
    g.reset(len(grids), xinit=xinit)
    g.poke(rst_n=0, enable=0, I=0)
    g.edge()
    g.edge()
    g.poke(rst_n=g.M, enable=g.M)
    mid = {nm: 0 for nm in midwatch}
    for i in range(FRAME):
        g.poke(I=lanes[i])
        g.edge()
        for nm in midwatch:
            mid[nm] |= g.get(nm) & (1 << i)
    g.poke(I=0)
    snap = {nm: g.get(nm) for nm in watch}
    succ = g.get("success")
    obytes = []
    for _ in range(tail):
        obytes.append(g.bus("O", 8))
        g.edge()
        succ |= g.get("success")
    return succ, obytes, snap, mid


def decode_stream(obytes, lane):
    """One character per clock, blanks dropped, runs collapsed."""
    out, prev = [], None
    for bits in obytes:
        v = sum(1 << b for b in range(8) if (bits[b] >> lane) & 1)
        if v != prev and 32 <= v < 127:
            out.append(chr(v))
        prev = v
    return "".join(out)


def per_cycle(obytes, lane):
    return [sum(1 << b for b in range(8) if (bits[b] >> lane) & 1) for bits in obytes]


# ---------------------------------------------------------------------------
# validating against the recorded silicon
# ---------------------------------------------------------------------------

def read_vcd(path):
    """Return (header fields, {name: id}, [(t, id, value)] in file order)."""
    txt = open(path).read()
    head = {}
    for f in ("date", "version", "timescale"):
        m = re.search(r"\$" + f + r"\s+(.*?)\s*\$end", txt, re.S)
        if m:
            head[f] = m.group(1).strip()
    sym = {}
    for w, ident, nm in re.findall(
            r"\$var\s+\w+\s+(\d+)\s+(\S+)\s+([^\s$]+)", txt):
        sym[ident] = nm
    ev, t = [], 0
    for line in txt.splitlines():
        line = line.strip()
        if not line:
            continue
        if line[0] == "#":
            t = int(line[1:])
        elif line[0] in "01xzXZ" and len(line) >= 2 and line[1:] in sym:
            ev.append((t, line[1:], line[0]))
        else:
            m = re.match(r"^[bB](\S+)\s+(\S+)$", line)
            if m and m.group(2) in sym:
                ev.append((t, m.group(2), m.group(1)))
    return head, {v: k for k, v in sym.items()}, ev


def vcd_replay(g, vcd_path, out_path):
    """Replay the recorded waveform through the extracted netlist.

    example_inputs.vcd is a recording of the real chip: known inputs and the
    outputs it actually produced. Driving the same inputs into a netlist built
    from nothing but polygon coordinates, and getting the same outputs back, is
    the strongest check available without an answer key, because the trace
    cannot have been tuned against.
    """
    head, byname, ev = read_vcd(vcd_path)
    ids = {nm: byname[nm] for nm in ("clk", "rst_n", "enable", "I", "O", "success")}
    rid = {v: k for k, v in ids.items()}
    groups = collections.OrderedDict()
    for t, ident, val in ev:
        groups.setdefault(t, []).append((ident, val))

    cur = {"clk": "0", "rst_n": "0", "enable": "0", "I": "0"}
    rec = {"O": "x", "success": "x"}
    g.reset(1)
    checks = mism = nedge = 0
    firstsucc = None
    rows = []
    for t, evs in groups.items():
        named = [(rid[i], v) for i, v in evs if i in rid]
        rise = any(nm == "clk" and v == "1" for nm, v in named) and cur["clk"] != "1"
        for nm, v in named:
            if nm in cur and nm != "clk":
                cur[nm] = v
        if rise:
            g.poke(rst_n=int(cur["rst_n"] == "1"), enable=int(cur["enable"] == "1"),
                   I=int(cur["I"] == "1"))
            g.edge()
            nedge += 1
        for nm, v in named:
            if nm in rec:
                rec[nm] = v
            elif nm == "clk":
                cur["clk"] = v
        if not rise:
            continue
        got = {"O": g.byte("O", 0), "success": g.get("success") & 1}
        if got["success"] and firstsucc is None:
            firstsucc = nedge
        for nm in ("O", "success"):
            if not set(rec[nm]) <= set("01"):
                continue
            checks += 1
            if int(rec[nm], 2) != got[nm]:
                mism += 1
                if len(rows) < 12:
                    rows.append(f"  MISMATCH edge {nedge} t={t} {nm} "
                                f"chip={int(rec[nm], 2)} netlist={got[nm]}")
    L = ["REPLAY OF THE RECORDED SILICON WAVEFORM", "=" * 70, "",
         f"source            {os.path.relpath(vcd_path, ROOT)}",
         f"$date             {head.get('date')!r}",
         f"$version          {head.get('version')!r}",
         f"rising clk edges  {nedge}",
         f"outputs compared  {checks}",
         f"mismatches        {mism}",
         f"success ever high {'yes at edge %d' % firstsucc if firstsucc else 'no'}", ""]
    L += rows
    L.append("RESULT: a netlist recovered from raw polygons reproduces the recorded"
             if mism == 0 else "RESULT: MISMATCH. Stop here.")
    if mism == 0:
        L.append("        chip outputs exactly, at every compared edge.")
    write(out_path, "\n".join(L))
    return checks, mism, nedge


def write_vcd(path, trace, period=10000):
    """Write a VCD shaped like example_inputs.vcd so the two open side by side."""
    ids = {"clk": "!", "rst_n": '"', "enable": "#", "I": "$", "O": "%", "success": "&"}
    L = ["$date", "  Recovered by GDS-to-RTL/gds_to_rtl.py from puzzle.gds", "$end",
         "$version", "  The night sky awaits.", "$end",
         "$timescale", "\t1ps", "$end"]
    for nm, w in (("clk", 1), ("rst_n", 1), ("enable", 1), ("I", 1), ("O", 8),
                  ("success", 1)):
        L.append("$scope module puzzle $end")
        L.append(f"$var {'reg' if w == 1 else 'wire'} {w} {ids[nm]} {nm}"
                 + (f" [{w-1}:0]" if w > 1 else "") + " $end")
        L.append("$upscope $end")
    L += ["$enddefinitions $end", "$dumpvars", "x&", "bx %", "0$", "0#", "0\"", "0!",
          "$end"]
    prev = {}
    for t, vals in trace:
        chunk = []
        for nm, v in vals.items():
            if prev.get(nm) == v:
                continue
            prev[nm] = v
            if nm == "O":
                chunk.append(f"b{v:b} %" if v else "b0 %")
            else:
                chunk.append(f"{v}{ids[nm]}")
        if chunk:
            L.append(f"#{t}")
            L += chunk
    return write(path, "\n".join(L))


def make_success_vcd(g, bits, path):
    """Simulate the winning grid and record it exactly as the sample file is shaped."""
    g.reset(1)
    trace, t = [], 0
    half = 5000

    def snap():
        return {"clk": 1, "rst_n": g.get("rst_n") & 1, "enable": g.get("enable") & 1,
                "I": g.get("I") & 1, "O": g.byte("O", 0),
                "success": g.get("success") & 1}

    sched = [(0, 0, 0)] * 3 + [(1, 0, 0)] + \
            [(1, 1, int(b)) for b in bits] + [(1, 1, 0)] * 30
    firstsucc = None
    for k, (rst, en, i) in enumerate(sched):
        g.poke(rst_n=rst, enable=en, I=i)
        t = half + k * 2 * half
        g.edge()
        s = snap()
        if s["success"] and firstsucc is None:
            firstsucc = (k + 1, t)
        trace.append((t - half + 1, {"clk": 0, "rst_n": rst, "enable": en, "I": i}))
        trace.append((t, {"clk": 1}))
        trace.append((t + 1, s))
        trace.append((t + half, {"clk": 0}))
    write_vcd(path, trace)
    return firstsucc


# ---------------------------------------------------------------------------
# register-level structure
# ---------------------------------------------------------------------------

def decompile(g, ast, wrap=76):
    """Expand a logic cone into a boolean expression, stopping at flops and ports.

    Useful for the small control cones and useless for the counters, whose 22
    cones expand into megabytes of repeated subexpression. The counters are
    probed instead.
    """
    combof = {o: a for o, a in g.comb}
    label = {}
    for f in g.flops:
        if f["q"] is not None:
            label[f["q"]] = f["inst"].split("_")[0] + ".Q"
        if f["qn"] is not None:
            label[f["qn"]] = f["inst"].split("_")[0] + ".QN"

    def go(node, depth=0):
        k = node[0]
        if k == "c":
            return "1" if node[1] else "0"
        if k == "n":
            n = node[1]
            if n in label:
                return label[n]
            if n in combof and depth < 40:
                return go(combof[n], depth + 1)
            return g.names[n]
        if k == "!":
            inner = go(node[1], depth)
            return f"!{inner}" if re.match(r"^[\w.]+$", inner) else f"!({inner})"
        return f"({go(node[1], depth)} {k} {go(node[2], depth)})"

    text = go(ast)
    out, line = [], ""
    for tok in re.findall(r"!*[\w.]+|!*\(|[)&|^]|\s+", text):
        if len(line) + len(tok) > wrap and tok.strip():
            out.append(line.rstrip())
            line = "    "
        line += tok
    out.append(line.rstrip())
    return "\n".join(out)


def structure(g, out_path):
    """Rebuild the register graph and find its feedback groups.

    A gate netlist has no hierarchy: 728 cells in one bag. One node per
    flip-flop and an edge a->b when Q(a) is in the combinational fan-in of D(b)
    puts the architecture back. Strongly connected components in that graph are
    the counters and state machines, because a feedback loop is the one thing
    synthesis cannot flatten away.
    """
    combof = {o: a for o, a in g.comb}
    qof = {f["q"]: f["inst"] for f in g.flops if f["q"] is not None}
    qof.update({f["qn"]: f["inst"] for f in g.flops if f["qn"] is not None})
    memo = {}

    def srcs(n):
        if n in memo:
            return memo[n]
        memo[n] = out = set()
        if n in qof:
            out.add(("FF", qof[n]))
            return out
        a = combof.get(n)
        if a is None:
            out.add(("PORT", g.names[n]))
            return out
        acc = set()
        for d in ast_nets(a, set()):
            acc |= srcs(d)
        memo[n] = acc
        return acc

    edges = {}
    for f in g.flops:
        s = set()
        for a in (f["d"], f["clr"], f["pre"]):
            if a is None:
                continue
            for d in ast_nets(a, set()):
                s |= srcs(d)
        edges[f["inst"]] = s
    fan = collections.defaultdict(set)
    for b, s in edges.items():
        for kind, nm in s:
            if kind == "FF":
                fan[nm].add(b)

    flops = [f["inst"] for f in g.flops]
    order = {nm: i for i, nm in enumerate(flops)}
    graph = {a: sorted(fan[a], key=lambda x: order[x]) for a in flops}
    index, low, onstk, stk, comps, ctr = {}, {}, set(), [], [], [0]
    for root in flops:
        if root in index:
            continue
        work = [(root, iter(graph[root]))]
        index[root] = low[root] = ctr[0]
        ctr[0] += 1
        stk.append(root)
        onstk.add(root)
        while work:
            v, it = work[-1]
            adv = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = ctr[0]
                    ctr[0] += 1
                    stk.append(w)
                    onstk.add(w)
                    work.append((w, iter(graph[w])))
                    adv = True
                    break
                if w in onstk:
                    low[v] = min(low[v], index[w])
            if adv:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stk.pop()
                    onstk.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                comps.append(sorted(comp, key=lambda x: order[x]))
    sccs = sorted((c for c in comps if len(c) > 1),
                  key=lambda c: (-len(c), order[c[0]]))
    pairs = [tuple(c) for c in sccs if len(c) == 2]
    succ = srcs(g.idx["success"])

    L = ["REGISTER-LEVEL STRUCTURE OF THE RECOVERED NETLIST", "=" * 70, "",
         f"logic cells      {len(g.cellof)}",
         f"nets             {len(g.names)}",
         f"flip-flops       {len(g.flops)}  "
         f"{dict(collections.Counter(g.cellof[f] for f in flops))}",
         f"clock roots      {sorted(g.clock_tree())}",
         f"feedback groups  {len(sccs)}",
         f"  of size 2      {len(pairs)}   <- two-bit counters",
         ""]
    L.append("FEEDBACK GROUPS (Tarjan SCC over the register graph)")
    L.append("-" * 70)
    for c in sccs:
        ext = sorted({nm for f in c for kind, nm in edges[f] if kind == "PORT"})
        L.append(f"  size {len(c):2d}  ports {ext or 'none'}")
        L.append(f"           {' '.join(c)}")
    L += ["", "WHAT success DEPENDS ON", "-" * 70,
          f"  {len([1 for k, _ in succ if k == 'FF'])} flip-flops, "
          f"ports {sorted(nm for k, nm in succ if k == 'PORT')}",
          f"  {sorted(nm for k, nm in succ if k == 'FF')}", ""]
    L += ["WHAT O[7:0] DEPENDS ON", "-" * 70]
    for b in range(8):
        s = srcs(g.idx[f"O[{b}]"])
        L.append(f"  O[{b}]  {len([1 for k, _ in s if k == 'FF'])} flip-flops, "
                 f"ports {sorted(nm for k, nm in s if k == 'PORT')}")
    succ_ff = sorted(nm for k, nm in succ if k == "FF")
    if len(succ_ff) == 1:
        f = next(x for x in g.flops if x["inst"] == succ_ff[0])
        L += ["", f"THE SET CONDITION OF {succ_ff[0]}, DECOMPILED", "-" * 70,
              "Expanded through the combinational logic and stopped at flip-flop",
              "outputs and ports. The structure is a wide AND tree that decomposes",
              "into two groups of eleven near-identical two-bit comparisons, every",
              "one of them against the value two.", "",
              "  D = " + decompile(g, f["d"]).lstrip(), "",
              "The same treatment on any of the 23 counter pairs expands into megabytes",
              "of repeated subexpression. Decompiling works for the control logic and",
              "fails for the counters, so the counters get probed instead."]
    write(out_path, "\n".join(L))
    return {"sccs": sccs, "pairs": pairs, "edges": edges, "succ_ff": succ_ff}


# ---------------------------------------------------------------------------
# read the hidden data straight out of the gates
# ---------------------------------------------------------------------------

def probe_regions(g, pairs, out_path, gds_path=None):
    """121 single-cell trials, all in one bit-parallel pass.

    Reading the logic cone of a counter tells you it is gated on some value; it
    does not tell you what that value means physically. So stop reading and start
    poking: put a star at exactly one grid position, clock the whole frame
    through, and see which counters moved. A counter that ticks for cell (r,c) is
    watching cell (r,c). No inference, no algebra.
    """
    flops = [f for p in pairs for f in p]
    qnet = {f["inst"]: f["q"] for f in g.flops}
    nets = [g.names[qnet[f]] for f in flops]
    single = ["0" * k + "1" + "0" * (FRAME - 1 - k) for k in range(FRAME)]
    succ, _, snap, mid = run_grids(g, single, watch=nets, midwatch=nets)
    end = {f: snap[g.names[qnet[f]]] for f in flops}
    now = {f: mid[g.names[qnet[f]]] for f in flops}

    watch, live = {}, {}
    for pi, (a, b) in enumerate(pairs):
        m = end[a] | end[b]
        watch[pi] = sorted(k for k in range(FRAME) if (m >> k) & 1)
        m2 = now[a] | now[b]
        live[pi] = sorted(k for k in range(FRAME) if (m2 >> k) & 1)

    rows, cols, other = [], [], []
    for pi, cells in watch.items():
        rs = {c // N for c in cells}
        cs = {c % N for c in cells}
        if not cells:
            rows.append(pi)
        elif len(cells) == N and len(rs) == 1:
            cols.append((pi, -1 - rs.pop()))
        elif len(cells) == N and len(cs) == 1:
            cols.append((pi, cs.pop()))
        else:
            other.append(pi)
    other.sort(key=lambda pi: min(watch[pi]))
    label = {}
    for i, pi in enumerate(other):
        for c in watch[pi]:
            label[c] = ALPHA[i]

    L = ["THE CONSTRAINT MAP, RECOVERED BY PROBING", "=" * 70, "",
         f"trials            {FRAME} (one star, one cell, nothing else)",
         f"two-bit counters  {len(pairs)}",
         f"grids accepted    {bin(succ).count('1')}", "",
         "WHAT EACH COUNTER WATCHES", "-" * 70]
    kindof = dict([(pi, "ROW, shared") for pi in rows]
                  + [(pi, f"COLUMN {c}") for pi, c in cols]
                  + [(pi, "REGION " + ALPHA[other.index(pi)]) for pi in other])
    for pi in sorted(watch, key=lambda p: (kindof[p][:3], watch[p])):
        L.append(f"  {pairs[pi][0]:16s} {pairs[pi][1]:16s} "
                 f"{len(watch[pi]):3d} cells at end of frame, "
                 f"{len(live[pi]):3d} the moment the star arrives   {kindof[pi]}")
    L += ["",
          f"row counters {len(rows)}   column counters {len(cols)}   "
          f"irregular groups {len(other)}",
          "",
          "There are eleven column counters and eleven region counters, not "
          "thirty-three.",
          "The eleven rows share one counter, and at the end of the frame it is always",
          "zero, so a naive read says it watches nothing. Sampling it in the cycle each",
          f"star arrives instead: {len(rows) and len(live[rows[0]])} of 121 trials move "
          "it. The 11 that do not are exactly",
          f"  {sorted(set(range(FRAME)) - set(live[rows[0]])) if rows else []}",
          "which is column 10 of every row: the last cell of a row, where the counter is",
          "cleared in the same cycle it is bumped. One counter, cleared at every row",
          "boundary, only works if the grid arrives row-major at one cell per clock, so",
          "exactly one row is ever in flight, which gives the input format.",
          "", "REGION MAP", "-" * 70,
          "     " + " ".join(f"{c:2d}" for c in range(N))]
    for r in range(N):
        L.append(f"  {r:2d} " + "  ".join(label.get(r * N + c, "?") for c in range(N)))
    sizes = collections.Counter(label.values())
    L += ["", f"  region sizes {dict(sorted(sizes.items()))}  sum "
              f"{sum(sizes.values())}",
          f"  cells with no region: "
          f"{[c for c in range(FRAME) if c not in label] or 'none'}",
          "",
          "Eleven irregular contiguous blobs that tile the grid, plus two per row,",
          "two per column and a no-touch rule. That is a Star Battle.", ""]

    if gds_path:
        L += floorplan(gds_path, pairs, watch, kindof)
    write(out_path, "\n".join(L))
    return {"watch": watch, "live": live, "label": label, "kind": kindof,
            "rows": rows, "cols": cols, "other": other,
            "sizes": dict(sorted(sizes.items()))}


def floorplan(gds_path, pairs, watch, kindof):
    """Put the recovered counters back on the die. The blog said to look at the layout."""
    top = gdstk.read_gds(gds_path).top_level()[0]
    pos, i = {}, 0
    for ref in top.references:
        nm = ref.cell.name
        if not nm.startswith("sky130_fd_sc_hd__"):
            continue
        if nm.split("__")[-1].startswith(PHYS_PREFIX):
            continue
        pos[i] = (ref.origin[0], ref.origin[1])
        i += 1
    at = lambda inst: pos.get(int(inst.split("_")[0][1:]), (0, 0))
    rows = []
    for pi, (a, b) in enumerate(pairs):
        xa, ya = at(a)
        xb, yb = at(b)
        rows.append(((xa + xb) / 2, (ya + yb) / 2, kindof[pi], len(watch[pi]),
                     f"{a}+{b}"))
    rows.sort(key=lambda r: r[1])
    bb = top.bounding_box()
    L = ["WHERE THE COUNTERS SIT ON THE DIE", "-" * 70,
         f"  die ({bb[0][0]:.1f}, {bb[0][1]:.1f}) .. ({bb[1][0]:.1f}, {bb[1][1]:.1f}) um",
         f"  {'x':>8} {'y':>8}  {'what':12s} cells  flops"]
    for x, y, k, n, nm in rows:
        L.append(f"  {x:8.2f} {y:8.2f}  {k:10s} {n:5d}  {nm}")
    stack = [r for r in rows if not r[2].startswith("ROW")]
    cy = [r[1] for r in rows if r[2].startswith("COL")]
    ry = [r[1] for r in rows if r[2].startswith("REG")]
    rowsl = [r for r in rows if r[2].startswith("ROW")]
    L += ["",
          f"  the checker is one vertical column at x = "
          f"{min(r[0] for r in stack):.1f} .. {max(r[0] for r in stack):.1f} um "
          f"of a {bb[1][0]-bb[0][0]:.0f} um wide die",
          f"  {len(cy):2d} column slices  y = {min(cy):.1f} .. {max(cy):.1f}",
          f"     a gap         y = {max(ry):.1f} .. {min(cy):.1f}",
          f"  {len(ry):2d} region slices  y = {min(ry):.1f} .. {max(ry):.1f}"]
    if rowsl:
        L.append(f"   1 row slice     off to the side at x = {rowsl[0][0]:.1f}, "
                 f"y = {rowsl[0][1]:.1f}")
    L += ["", "  11 column counters, 11 region counters and 1 shared row counter,",
          "  all placed in one column of the die.", ""]
    return L


# ---------------------------------------------------------------------------
# SAT: hand the recovered gates to a solver
# ---------------------------------------------------------------------------

class CNF:
    """Tseitin encoder. Variable 1 is pinned true, so -1 is a usable false.

    Two cheap things happen while the clauses are being written. A gate whose
    inputs are already constants, or are the same literal, or are opposite
    literals, folds to a literal instead of minting a variable. And a gate whose
    (operator, inputs) triple has been written before hands back the variable
    that was minted then, so the formula carries one copy of each distinct piece
    of logic. Reset pins a large part of the design to a constant for the first
    steps of an unrolling and the eleven region counters are near duplicates of
    each other, so between them the two rules take a real bite out of the
    formula before the solver ever sees it. Both preserve the encoded function
    exactly: a Tseitin definition depends on nothing but its own operator and
    inputs.
    """

    def __init__(self):
        self.n = 1
        self.cls = [[1]]
        self.seen = {}
        self.folded = 0
        self.shared = 0

    def var(self):
        self.n += 1
        return self.n

    def add(self, *c):
        self.cls.append(list(c))

    def fold(self, op, a, b):
        """The literal this gate is equal to outright, or None if it needs a variable."""
        if op == "&":
            if a == 1 or a == b:
                return b
            if b == 1:
                return a
            if a == -1 or b == -1 or a == -b:
                return -1
        elif op == "|":
            if a == -1 or a == b:
                return b
            if b == -1:
                return a
            if a == 1 or b == 1 or a == -b:
                return 1
        else:
            if a == 1:
                return -b
            if b == 1:
                return -a
            if a == -1:
                return b
            if b == -1:
                return a
            if a == b:
                return -1
            if a == -b:
                return 1
        return None

    def gate(self, op, a, b=None):
        r = self.fold(op, a, b)
        if r is not None:
            self.folded += 1
            return r
        k = (op, a, b) if a <= b else (op, b, a)
        o = self.seen.get(k)
        if o is not None:
            self.shared += 1
            return o
        o = self.var()
        ap = self.cls.append
        if op == "&":
            ap([-a, -b, o]), ap([a, -o]), ap([b, -o])
        elif op == "|":
            ap([a, b, -o]), ap([-a, o]), ap([-b, o])
        else:
            ap([-a, -b, -o]), ap([a, b, -o]), ap([a, -b, o]), ap([-a, b, o])
        self.seen[k] = o
        return o


def unroll(g, steps, free_inputs, fixed, xfree=True, cone=None, initfree=False):
    """Time-unroll the recovered netlist into CNF.

    Step t settles the combinational logic from the state left by step t-1 and
    the inputs applied on edge t, then the flops capture. So the value of a net
    at step t+1 is what a probe would read after t clock edges. Encoding this
    from the same parsed Liberty functions the simulator uses means the thing
    handed to the solver is the same circuit, not a paraphrase of it.
    """
    cnf = CNF()
    TRUE, FALSE = 1, -1
    combof = {o: a for o, a in g.comb}
    keep = cone if cone is not None else set(range(len(g.names)))
    lit = [dict() for _ in range(steps + 2)]
    invars = collections.defaultdict(dict)

    for f in g.flops:
        v = TRUE if f["init"] else FALSE
        if initfree or (f["clr"] is None and f["pre"] is None and xfree):
            v = cnf.var()
        if f["q"] is not None:
            lit[1][f["q"]] = v
        if f["qn"] is not None:
            lit[1][f["qn"]] = -v

    def enc(t, node):
        k = node[0]
        if k == "c":
            return TRUE if node[1] else FALSE
        if k == "n":
            return net(t, node[1])
        if k == "!":
            return -enc(t, node[1])
        return cnf.gate(k, enc(t, node[1]), enc(t, node[2]))

    def net(t, n):
        if n in lit[t]:
            return lit[t][n]
        nm = g.names[n]
        if nm in g.ports and g.ports[nm] == "input":
            if nm in fixed:
                r = TRUE if fixed[nm] else FALSE
            elif nm in free_inputs:
                r = cnf.var()
                invars[nm][t] = r
            else:
                r = FALSE
        elif n in combof:
            r = enc(t, combof[n])
        else:
            r = FALSE
        lit[t][n] = r
        return r

    for t in range(1, steps + 1):
        for f in g.flops:
            if f["q"] is not None and f["q"] not in keep:
                continue
            d = enc(t, f["d"])
            clr = enc(t, f["clr"]) if f["clr"] else FALSE
            pre = enc(t, f["pre"]) if f["pre"] else FALSE
            q = cnf.gate("&", -clr, cnf.gate("|", pre, d))
            if f["q"] is not None:
                lit[t + 1][f["q"]] = q
            if f["qn"] is not None:
                lit[t + 1][f["qn"]] = -q
    return cnf, lit, invars, net


def cone_of(g, targets):
    """Everything the given nets depend on, through logic and through flops."""
    combof = {o: a for o, a in g.comb}
    dof = {}
    for f in g.flops:
        for k in ("q", "qn"):
            if f[k] is not None:
                dof[f[k]] = f
    need, stack = set(), list(targets)
    while stack:
        n = stack.pop()
        if n in need:
            continue
        need.add(n)
        if n in combof:
            stack += list(ast_nets(combof[n], set()))
        elif n in dof:
            f = dof[n]
            for a in (f["d"], f["clr"], f["pre"]):
                if a is not None:
                    stack += list(ast_nets(a, set()))
    return need


def solver(cnf):
    """The SAT back end, loaded with a formula.

    python-sat ships several. This one was picked by running the two workloads
    this pipeline actually has, the depth question in P8 and the fourteen
    incremental enumeration queries in P10, against each of them and taking the
    fastest total. The numbers are in GDS-to-RTL/summary.md; nothing else in the
    pipeline depends on which name sits here.
    """
    import pysat.solvers
    return getattr(pysat.solvers, SAT_BACKEND)(bootstrap_with=cnf.cls)


def sat_solve(cnf, assume=(), extra=()):
    s = solver(cnf)
    for c in extra:
        s.add_clause(c)
    ok = s.solve(assumptions=list(assume))
    m = set(s.get_model()) if ok else None
    s.delete()
    return ok, m


class Sat:
    """One solver kept alive across queries, so a big unrolling is encoded once.

    eq() mints a variable that is true exactly when a bus carries a given value,
    which lets a whole enumeration run on assumptions rather than on permanent
    blocking clauses.
    """

    def __init__(self, cnf):
        self.cnf = cnf
        self.s = solver(cnf)
        self.cache = {}

    def eq(self, key, lits, val):
        if (key, val) in self.cache:
            return self.cache[(key, val)]
        o = self.cnf.var()
        want = [l if (val >> b) & 1 else -l for b, l in enumerate(lits)]
        for w in want:
            self.s.add_clause([-o, w])
        self.s.add_clause([o] + [-w for w in want])
        self.cache[(key, val)] = o
        return o

    def solve(self, assume=()):
        ok = self.s.solve(assumptions=list(assume))
        return ok, (set(self.s.get_model()) if ok else None)

    def close(self):
        self.s.delete()


def linearity(g, trials=20, seed=20260817):
    """Is the frame's state update linear over GF(2)?

    If it were, the chip would be an LFSR or a CRC and Gaussian elimination
    would invert it in milliseconds, no solver required. The test is the
    definition: for random input frames u and v, a linear map satisfies
    F(u xor v) = F(u) xor F(v) xor F(0). Run u, v and u xor v as three lanes of
    one bit-parallel pass and compare all 92 flops.
    """
    import random
    rnd = random.Random(seed)
    grids = ["0" * FRAME]
    for _ in range(trials):
        u = "".join(rnd.choice("01") for _ in range(FRAME))
        v = "".join(rnd.choice("01") for _ in range(FRAME))
        x = "".join("1" if a != b else "0" for a, b in zip(u, v))
        grids += [u, v, x]
    nets = [g.names[f["q"]] for f in g.flops if f["q"] is not None]
    _, _, snap, _ = run_grids(g, grids, watch=nets)
    bit = lambda nm, k: (snap[nm] >> k) & 1
    bad = 0
    for t in range(trials):
        u, v, x = 1 + 3 * t, 2 + 3 * t, 3 + 3 * t
        if any(bit(nm, x) != (bit(nm, u) ^ bit(nm, v) ^ bit(nm, 0)) for nm in nets):
            bad += 1
    return trials, bad


def grid_props(bits, label):
    """Everything the chip is known to count, measured on one grid."""
    rows = [sum(int(bits[r * N + c]) for c in range(N)) for r in range(N)]
    cols = [sum(int(bits[r * N + c]) for r in range(N)) for c in range(N)]
    per = collections.Counter(label[k] for k in range(FRAME) if bits[k] == "1")
    touch = 0
    for r in range(N):
        for c in range(N):
            if bits[r * N + c] != "1":
                continue
            for dr, dc in ((0, 1), (1, -1), (1, 0), (1, 1)):
                if 0 <= r + dr < N and 0 <= c + dc < N \
                        and bits[(r + dr) * N + c + dc] == "1":
                    touch += 1
    return {"stars": bits.count("1"),
            "rows2": all(x == 2 for x in rows),
            "cols2": all(x == 2 for x in cols),
            "regions2": all(per.get(k, 0) == 2 for k in set(label.values())),
            "touching": touch}


def catalogue(g, label, out_path, first_edge=FRAME + 1):
    """Every string the chip can be made to print, with a proof the list is complete.

    Reading a verdict off a grid you guessed is luck. Instead the netlist is
    unrolled from reset with all 121 input bits free, and the solver is asked to
    enumerate every value the output bus can take on the first output edge, then
    every value it can take on the second given the first. Two characters are
    enough to separate the messages, so when the enumeration comes back UNSAT the
    catalogue is closed: nothing else is reachable.

    Each surviving prefix then hands back the grid that produced it, which gets
    simulated to read the rest of the string and measured to say what class of
    mistake triggers it.
    """
    steps = first_edge + 3
    keep = cone_of(g, [g.idx[f"O[{b}]"] for b in range(8)] + [g.idx["success"]])
    cnf, lit, invars, netf = unroll(
        g, steps, ["I"], {"rst_n": 1, "enable": 1, "clk": 1}, cone=keep)
    obus = {t: [netf(t, g.idx[f"O[{b}]"]) for b in range(8)]
            for t in (first_edge + 1, first_edge + 2)}
    sat = Sat(cnf)
    queries = [0]

    def values(t, prefix):
        found, block = [], []
        while True:
            ok, m = sat.solve(prefix + block)
            queries[0] += 1
            if not ok:
                return found
            v = sum(1 << b for b in range(8) if obus[t][b] in m)
            found.append((v, m))
            block.append(-sat.eq(t, obus[t], v))

    t1, t2 = first_edge + 1, first_edge + 2
    prefixes = []
    for v1, _ in values(t1, []):
        p1 = [sat.eq(t1, obus[t1], v1)]
        for v2, m in values(t2, p1):
            prefixes.append((v1, v2, m))
    nq = queries[0]
    sat.close()

    rows = []
    for v1, v2, m in prefixes:
        bits = "".join("1" if invars["I"][t] in m else "0"
                       for t in sorted(invars["I"])[:FRAME])
        succ, ob, _, _ = run_grids(g, [bits], tail=40)
        rows.append((decode_stream(ob, 0), succ & 1, bits, grid_props(bits, label)))
    rows.sort(key=lambda r: r[0])

    L = ["EVERY STRING THE CHIP CAN PRINT", "=" * 70, "",
         f"The netlist is unrolled from reset over {steps} steps with all 121 input",
         "bits left free, and the solver enumerates the output bus one character at",
         "a time. Two characters separate every message, so the enumeration closing",
         "with UNSAT means this list is the whole ROM.",
         "",
         f"first characters reachable on edge {t1 - 1}:   "
         f"{sorted({chr(v) for v, _, _ in prefixes})}",
         f"distinct two-character prefixes:  {len(prefixes)}",
         f"SAT queries                       {nq}", "",
         "THE CATALOGUE", "-" * 70,
         f"  {'message':17s} {'success':7s} {'stars':5s} {'2/row':6s} {'2/col':6s} "
         f"{'2/region':9s} {'touching pairs'}"]
    for msg, s, bits, p in rows:
        L.append(f"  {msg!r:17s} {s:^7d} {p['stars']:5d} "
                 f"{str(p['rows2']):6s} {str(p['cols2']):6s} "
                 f"{str(p['regions2']):9s} {p['touching']}")
    L += ["", "WHAT TRIGGERS EACH ONE", "-" * 70]
    for msg, s, bits, p in rows:
        if p["stars"] == 0:
            why = "an empty grid"
        elif p["stars"] == FRAME:
            why = "every cell a star"
        elif p["rows2"] and p["cols2"] and p["regions2"] and not p["touching"]:
            why = "the one grid that satisfies every rule"
        elif p["rows2"] and p["cols2"] and p["regions2"]:
            why = ("every count correct, two stars per row, per column and per "
                   "region, but at least one touching pair")
        else:
            why = "any other wrong grid"
        L.append(f"  {msg!r:17s} {why}")
    L += ["", "AN EXAMPLE GRID FOR EACH", "-" * 70]
    for msg, s, bits, p in rows:
        L.append(f"  {msg}   ({bits.count('1')} stars)")
        for r in range(N):
            L.append("     " + " ".join("*" if bits[r * N + c] == "1" else "."
                                        for c in range(N)))
        L.append("")
    L += ["TWO NOT TOUCH is the other name of Star Battle. The chip prints it only",
          "when every count is correct and the no-touch rule is the one broken, which",
          "is a class of grid a random sweep does not reach.",
          ""]
    write(out_path, "\n".join(L))
    return rows, nq


def touching_grids(label, n):
    """Grids that satisfy every count but put two stars next to each other.

    These are the vectors that separate a four-message reading of the output
    generator from the true five-message one, and no random sweep produces them.
    """
    from z3 import And, Bool, If, Not, Or, Solver, Sum, is_true, sat
    G = [[Bool(f"t{r}_{c}") for c in range(N)] for r in range(N)]
    s = Solver()
    for r in range(N):
        s.add(Sum([If(G[r][c], 1, 0) for c in range(N)]) == STARS)
    for c in range(N):
        s.add(Sum([If(G[r][c], 1, 0) for r in range(N)]) == STARS)
    by = collections.defaultdict(list)
    for cell, lab in label.items():
        by[lab].append(cell)
    for cells in by.values():
        s.add(Sum([If(G[k // N][k % N], 1, 0) for k in cells]) == STARS)
    adj = []
    for r in range(N):
        for c in range(N):
            for dr, dc in ((0, 1), (1, -1), (1, 0), (1, 1)):
                if 0 <= r + dr < N and 0 <= c + dc < N:
                    adj.append(And(G[r][c], G[r + dr][c + dc]))
    s.add(Or(adj))
    out = []
    while len(out) < n and s.check() == sat:
        m = s.model()
        bits = "".join("1" if is_true(m.evaluate(G[r][c])) else "0"
                       for r in range(N) for c in range(N))
        out.append(bits)
        s.add(Or([G[r][c] != (bits[r * N + c] == "1")
                  for r in range(N) for c in range(N)]))
    return out


# ---------------------------------------------------------------------------
# the abstract puzzle, solved without looking at the chip
# ---------------------------------------------------------------------------

def star_battle(label, limit=None, regions=True):
    """Solve 2-per-row, 2-per-column, 2-per-region, no-touch with z3. All solutions."""
    from z3 import And, Bool, If, Not, Or, Solver, Sum, sat
    g = [[Bool(f"g{r}_{c}") for c in range(N)] for r in range(N)]
    s = Solver()
    for r in range(N):
        s.add(Sum([If(g[r][c], 1, 0) for c in range(N)]) == STARS)
    for c in range(N):
        s.add(Sum([If(g[r][c], 1, 0) for r in range(N)]) == STARS)
    if regions:
        by = collections.defaultdict(list)
        for cell, lab in label.items():
            by[lab].append(cell)
        for cells in by.values():
            s.add(Sum([If(g[k // N][k % N], 1, 0) for k in cells]) == STARS)
    for r in range(N):
        for c in range(N):
            for dr, dc in ((0, 1), (1, -1), (1, 0), (1, 1)):
                if 0 <= r + dr < N and 0 <= c + dc < N:
                    s.add(Not(And(g[r][c], g[r + dr][c + dc])))
    out = []
    while (limit is None or len(out) < limit) and s.check() == sat:
        m = s.model()
        grid = "".join("1" if bool(m.evaluate(g[r][c])) else "0"
                       for r in range(N) for c in range(N))
        out.append(grid)
        s.add(Or([g[r][c] != (grid[r * N + c] == "1")
                  for r in range(N) for c in range(N)]))
    return out, s.check() == sat


# ---------------------------------------------------------------------------
# the last step of the upstream flow: behavioural RTL
# ---------------------------------------------------------------------------

def emit_rtl(label, sol, hard, path, tbpath, top):
    table = "\n".join(f"      11'd{k}: region_id = 4'd{ord(label[k]) - 65};"
                      for k in range(FRAME))
    grid = "\n".join("//   " + " ".join(label[r * N + c] for c in range(N))
                     for r in range(N))
    hardn = len(hard)
    hardinit = "\n".join(f"    hard[{i}] = 121'b{b};" for i, b in enumerate(hard))
    rtl = f"""// ===========================================================================
// puzzle_recovered.v -- behavioural RTL for the chip in puzzle.gds
//
// An 11x11 Star Battle ("Two Not Touch") validator.
//
//   The grid arrives serially on I, one cell per rising clock while enable is
//   high, row-major: 121 cells, 121 clocks. A star is I=1. The grid is accepted
//   when every row, every column and every one of the 11 irregular regions holds
//   exactly two stars, no two stars touch even diagonally, and there are 22
//   stars in total.
//
//   success rises on the 122nd enabled rising edge and latches. O[7:0] streams
//   an ASCII verdict from that same edge, one character per clock. There are
//   five verdicts, and the fifth is the interesting one: a grid that gets every
//   count right and only breaks the no-touch rule is told TWO NOT TOUCH.
//
// Region map, read out of the gates by single-cell probing:
{grid}
// ===========================================================================
module puzzle_recovered (
  input  wire       clk,
  input  wire       rst_n,
  input  wire       I,
  input  wire       enable,
  output wire       success,
  output wire [7:0] O
);
  localparam N = 11;

  reg [3:0]  col, row;
  reg        done, done_d, succ_q;
  wire       running   = enable & ~done;
  wire       last_col  = (col == N-1);
  wire       last_cell = last_col & (row == N-1);
  wire       star      = I & running;

  reg  [3:0]  region_id;
  wire [10:0] cell_no = row * N + col;
  always @* begin
    region_id = 4'd0;
    case (cell_no)
{table}
    endcase
  end

  reg [1:0]   ccnt [0:N-1];
  reg [1:0]   gcnt [0:N-1];
  reg [1:0]   rowcnt;
  reg [7:0]   total;
  reg         adj_err, row_err;
  reg         all_ok;
  reg [N-1:0] prev_row, cur_row;
  reg         prev_cell;

  wire above_l = (col > 0)   ? prev_row[col-1] : 1'b0;
  wire above_c =               prev_row[col];
  wire above_r = (col < N-1) ? prev_row[col+1] : 1'b0;
  wire touches = prev_cell | above_l | above_c | above_r;

  integer i;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      col <= 0; row <= 0; done <= 0; done_d <= 0; succ_q <= 0;
      rowcnt <= 0; total <= 0; adj_err <= 0; row_err <= 0;
      prev_row <= 0; cur_row <= 0; prev_cell <= 0;
      for (i = 0; i < N; i = i + 1) begin ccnt[i] <= 0; gcnt[i] <= 0; end
    end else begin
      done_d <= done;
      if (running) begin
        if (star) begin
          if (ccnt[col]       != 2'd3) ccnt[col]       <= ccnt[col] + 1'b1;
          if (gcnt[region_id] != 2'd3) gcnt[region_id] <= gcnt[region_id] + 1'b1;
          if (rowcnt          != 2'd3) rowcnt          <= rowcnt + 1'b1;
          total        <= total + 1'b1;
          cur_row[col] <= 1'b1;
          if (touches) adj_err <= 1'b1;
        end
        prev_cell <= star;
        if (last_col) begin
          if ((rowcnt + (star && rowcnt != 2'd3)) != 2'd2) row_err <= 1'b1;
          rowcnt    <= 0;
          prev_cell <= 0;
          prev_row  <= cur_row | (star << col);
          cur_row   <= 0;
          col       <= 0;
          row       <= row + 1'b1;
          if (last_cell) done <= 1'b1;
        end else begin
          col <= col + 1'b1;
        end
      end
      if (done & ~done_d)
        succ_q <= ~adj_err & ~row_err & (total == 8'd22) & all_ok;
    end
  end

  always @* begin
    all_ok = 1'b1;
    for (i = 0; i < N; i = i + 1) begin
      if (ccnt[i] != 2'd2) all_ok = 1'b0;
      if (gcnt[i] != 2'd2) all_ok = 1'b0;
    end
  end

  assign success = succ_q;

  localparam MAXC = 16;
  reg [7:0] rom [0:MAXC-1];
  reg [4:0] optr, mlen;
  reg       emitting;
  reg [7:0] o_q;
  integer   j;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      optr <= 0; emitting <= 0; o_q <= 8'h00;
    end else if (done & ~done_d) begin
      emitting <= 1'b1; optr <= 5'd1; o_q <= rom[0];
    end else if (emitting && optr < mlen) begin
      o_q  <= rom[optr];
      optr <= optr + 1'b1;
    end else begin
      o_q <= 8'h00;
    end
  end
  assign O = o_q;

  wire counts_ok = ~row_err & (total == 8'd22) & all_ok;
  always @* begin
    if      (total == 8'd0)             j = 0;
    else if (total == 8'd121)           j = 1;
    else if (counts_ok & ~adj_err)      j = 2;
    else if (counts_ok &  adj_err)      j = 4;
    else                                j = 3;
    case (j)
      0: mlen = 9;  1: mlen = 8;  2: mlen = 15;  4: mlen = 13;  default: mlen = 9;
    endcase
  end
  always @* begin
    for (i = 0; i < MAXC; i = i + 1) rom[i] = 8'h00;
    case (j)
      0: begin rom[0]="E"; rom[1]="M"; rom[2]="P"; rom[3]="T"; rom[4]="Y";
               rom[5]=" "; rom[6]="S"; rom[7]="K"; rom[8]="Y"; end
      1: begin rom[0]="B"; rom[1]="I"; rom[2]="G"; rom[3]=" ";
               rom[4]="B"; rom[5]="A"; rom[6]="N"; rom[7]="G"; end
      2: begin rom[0]="("; rom[1]="*"; rom[2]=" "; rom[3]="T"; rom[4]="W";
               rom[5]="O"; rom[6]=" "; rom[7]="S"; rom[8]="T"; rom[9]="A";
               rom[10]="R"; rom[11]="S"; rom[12]=" "; rom[13]="*"; rom[14]=")"; end
      4: begin rom[0]="T"; rom[1]="W"; rom[2]="O"; rom[3]=" "; rom[4]="N";
               rom[5]="O"; rom[6]="T"; rom[7]=" "; rom[8]="T"; rom[9]="O";
               rom[10]="U"; rom[11]="C"; rom[12]="H"; end
      default: begin rom[0]="T"; rom[1]="R"; rom[2]="Y"; rom[3]=" ";
               rom[4]="A"; rom[5]="G"; rom[6]="A"; rom[7]="I"; rom[8]="N"; end
    endcase
  end
endmodule
"""
    write(path, rtl)
    tb = f"""`timescale 1ns/1ps
// Cycle equivalence: the netlist pulled out of puzzle.gds against the RTL
// written from an understanding of it. Both are driven from the same reset with
// the same stimulus and every cycle of success and O[7:0] is compared.
module tb_equiv;
  reg clk=0, rst_n=0, I=0, enable=0;
  wire s_gate, s_rtl;  wire [7:0] o_gate, o_rtl;
  integer t, c, mism, mism_o, seed, trial, nstar, r_i;
  integer shard, shards, ndone;
  integer perm [0:10]; integer perm2 [0:10];
  reg [120:0] g;
  reg [120:0] sol = 121'b{sol};
  reg [120:0] hard [0:{hardn} - 1];

  {top} uut_gate(.clk(clk), .rst_n(rst_n), .I(I), .enable(enable),
                 .success(s_gate), .O(o_gate));
  puzzle_recovered uut_rtl (.clk(clk), .rst_n(rst_n), .I(I), .enable(enable),
                            .success(s_rtl),  .O(o_rtl));
  always #5 clk = ~clk;

  task run_grid; input [120:0] grid; begin
    rst_n=0; enable=0; I=0;
    @(posedge clk); @(posedge clk); @(negedge clk);
    rst_n=1; enable=1;
    for (c=0; c<140; c=c+1) begin
      I = (c < 121) ? grid[120-c] : 1'b0;
      @(posedge clk);
      if (s_gate !== s_rtl) begin
        mism = mism + 1;
        if (mism < 5) $display("  MISMATCH success trial=%0d cycle=%0d gate=%b rtl=%b",
                               trial, c+1, s_gate, s_rtl);
      end
      if (o_gate !== o_rtl) begin
        mism_o = mism_o + 1;
        if (mism_o < 5) $display("  MISMATCH O trial=%0d cycle=%0d gate=%02h rtl=%02h",
                                 trial, c+1, o_gate, o_rtl);
      end
      @(negedge clk);
    end
    I=0; enable=0;
  end endtask

  // Every shard walks the same trial list and steps the same random stream, so
  // trial n is the same grid in all of them. Only its own share is simulated.
  task try_grid; input [120:0] grid; begin
    if (trial % shards == shard) begin
      ndone = ndone + 1;
      run_grid(grid);
    end
  end endtask

  initial begin
    mism = 0; mism_o = 0; seed = 1; ndone = 0;
    shard = 0; shards = 1;
    if ($value$plusargs("shard=%d", shard)) ;
    if ($value$plusargs("shards=%d", shards)) ;
{hardinit}
    trial = 0; try_grid(sol);
    trial = 1; try_grid(121'b0);
    trial = 2; try_grid({{121{{1'b1}}}});
    for (trial=3; trial<40; trial=trial+1) begin
      g = sol; t = {{$random(seed)}} % 121; g[t] = ~g[t]; try_grid(g);
    end
    for (trial=40; trial<240; trial=trial+1) begin
      g = 0; nstar = 1 + ({{$random(seed)}} % 30);
      for (c=0; c<nstar; c=c+1) g[{{$random(seed)}} % 121] = 1'b1;
      try_grid(g);
    end
    for (trial=240; trial<440; trial=trial+1) begin
      g = 0;
      for (r_i=0; r_i<11; r_i=r_i+1) begin
        g[120 - (r_i*11 + ({{$random(seed)}} % 11))] = 1'b1;
        g[120 - (r_i*11 + ({{$random(seed)}} % 11))] = 1'b1;
      end
      try_grid(g);
    end
    for (trial=440; trial<540; trial=trial+1) begin
      for (c=0; c<11; c=c+1) perm[c] = c;
      for (c=10; c>0; c=c-1) begin
        t = {{$random(seed)}} % (c+1);
        nstar = perm[c]; perm[c] = perm[t]; perm[t] = nstar;
      end
      for (c=0; c<11; c=c+1) perm2[c] = c;
      for (c=10; c>0; c=c-1) begin
        t = {{$random(seed)}} % (c+1);
        nstar = perm2[c]; perm2[c] = perm2[t]; perm2[t] = nstar;
      end
      g = 0;
      for (r_i=0; r_i<11; r_i=r_i+1) begin
        g[120 - (r_i*11 + perm[r_i])]  = 1'b1;
        g[120 - (r_i*11 + perm2[r_i])] = 1'b1;
      end
      try_grid(g);
    end
    for (trial=540; trial<540+{hardn}; trial=trial+1) try_grid(hard[trial-540]);
    $display("PARTIAL %0d %0d %0d", mism, mism_o, ndone);
    $finish;
  end
endmodule
"""
    write(tbpath, tb)


def iverilog(sources, tag, workdir, shards=1):
    """Compile once, then run vvp.

    Compiling 728 gates takes about 50 ms; simulating hundreds of 140-cycle
    grids through them is what costs. A testbench that reads +shard and +shards
    can run only the trials whose number falls in its shard while still stepping
    the same random stream, so the trial list is partitioned rather than
    resampled, and the shards go out to as many cores as the machine has. The
    results come back in shard order, so the transcript does not depend on which
    one finished first, and the shard count never appears in it.
    """
    exe = os.path.join(workdir, tag + ".vvp")
    r = subprocess.run(["iverilog", "-g2012", "-o", exe] + sources,
                       capture_output=True, text=True)
    if r.returncode:
        return None, (r.stdout + r.stderr)
    if shards <= 1:
        runs = [subprocess.run(["vvp", exe], capture_output=True, text=True)]
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=shards) as pool:
            runs = list(pool.map(
                lambda k: subprocess.run(
                    ["vvp", exe, f"+shard={k}", f"+shards={shards}"],
                    capture_output=True, text=True), range(shards)))
    os.remove(exe)
    keep = [l for run in runs for l in run.stdout.splitlines()
            if "$finish called" not in l]
    return "\n".join(keep) + "\n", None


# ---------------------------------------------------------------------------
# answer rendering
# ---------------------------------------------------------------------------

def answer_files(label, sol, msg, succ_edge, obytes_answer, out_dir):
    L = ["THE PUZZLE: 11x11 STAR BATTLE, ALSO CALLED TWO NOT TOUCH", "=" * 70, "",
         "Place two stars in every row, every column and every lettered region.",
         "No two stars may touch, not even diagonally.", "",
         "REGION MAP", "     " + " ".join(f"{c:2d}" for c in range(N))]
    for r in range(N):
        L.append(f"  {r:2d} " + "  ".join(label[r * N + c] for c in range(N)))
    L += ["", "THE UNIQUE SOLUTION", "     " + " ".join(f"{c:2d}" for c in range(N))]
    for r in range(N):
        L.append(f"  {r:2d} " + "  ".join("*" if sol[r * N + c] == "1" else "."
                                          for c in range(N)))
    L += ["", "SOLUTION OVER THE REGIONS",
          "     " + " ".join(f"{c:2d}" for c in range(N))]
    for r in range(N):
        L.append(f"  {r:2d} " + "  ".join("*" if sol[r * N + c] == "1"
                                          else label[r * N + c].lower()
                                          for c in range(N)))
    L += ["", "STAR COORDINATES, zero indexed"]
    for r in range(N):
        L.append(f"  row {r:2d}  columns "
                 f"{[c for c in range(N) if sol[r*N+c] == '1']}")
    rc = collections.Counter(label[k] for k in range(FRAME) if sol[k] == "1")
    L += ["", "CHECKS",
          "  row sums    " + " ".join(str(sum(int(sol[r * N + c]) for c in range(N)))
                                      for r in range(N)),
          "  column sums " + " ".join(str(sum(int(sol[r * N + c]) for r in range(N)))
                                      for c in range(N)),
          "  per region  " + " ".join(f"{k}={rc[k]}" for k in sorted(rc)),
          f"  total stars {sol.count('1')}"]
    write(os.path.join(out_dir, "11_solution_grid.txt"), "\n".join(L))

    S = ["HOW TO DRIVE THE CHIP", "=" * 70, "",
         "  rst_n   hold low for at least two clocks, then release high",
         "  enable  hold high for the whole run",
         "  I       one grid cell per rising clock edge, row-major",
         "          row 0 column 0 first, row 10 column 10 last, 121 bits",
         "",
         f"  success rises on enabled rising edge {succ_edge} and latches.",
         "  O[7:0] streams the ASCII verdict from that same edge, one character",
         f"  per clock, {len(msg)} characters.", "",
         "THE 121 BITS, row-major", "  " + sol, "", "SPLIT BY ROW"]
    for r in range(N):
        S.append(f"  row {r:2d}  {sol[r*N:(r+1)*N]}")
    S += ["", f"OUTPUT  {msg}"]
    write(os.path.join(out_dir, "12_input_sequence.txt"), "\n".join(S))

    O = ["WHAT THE CHIP PRINTS", "=" * 70, "",
         f"  {msg}", "",
         "O[7:0] cycle by cycle, counted in enabled rising edges", "-" * 70]
    prev = None
    for i, v in enumerate(obytes_answer):
        if v != prev:
            ch = chr(v) if 32 <= v < 127 else ""
            O.append(f"  edge {i+1:4d}  0x{v:02x}  {ch!r}" if ch
                     else f"  edge {i+1:4d}  0x{v:02x}")
        prev = v
    O += ["",
          "(* ... *) is Verilog attribute syntax and also an OCaml comment. Inside",
          "it is the rule the 728 gates check over the frame."]
    write(os.path.join(out_dir, "13_output_string.txt"), "\n".join(O))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def do_warmup(lib, use_iverilog):
    os.makedirs(WOUT, exist_ok=True)
    with stage("W1", "warm-up: inventory 04_final.gds"):
        inv = inventory(WARMUP_GDS, os.path.join(WOUT, "01_gds_inventory.txt"))
        say(f"top cell {inv['top']}, {inv['placements']} placements: "
            f"{inv['logic']} logic, {inv['via']} vias, {inv['phys']} physical")
        say(f"{inv['types']} logic cell types, ports "
            f"{sorted(set(inv['labels']) - POWER_PINS)}")

    with stage("W2", "warm-up: extract a netlist from the polygons"):
        net, ex = extract(WARMUP_GDS, WOUT, "02_extracted_netlist.v")
        for nm, sh, isl in ex["layers"]:
            say(f"{nm:5s} {sh:6d} shapes -> {isl:5d} islands")
        say(f"{ex['nets']} nets, {ex['logic']} logic cells, "
            f"{len(ex['bad'])} nets with a driver count other than one")

    with stage("W3", "warm-up: check it against the shipped DEF and netlist"):
        gc = golden_check(WARMUP_GDS, WARMUP_DEF, WARMUP_NET, ex,
                          os.path.join(WOUT, "04_golden_crosscheck.txt"))
        say(f"placements matched to DEF components {gc['matched']}/"
            f"{gc['matched'] + gc['unmatched']}")
        say(f"net partition vs 01_netlist.v: {gc['ok']} exact, {gc['bad']} mismatches, "
            f"golden has {gc['gold']} nets")
        write(os.path.join(WOUT, "07_name_map.json"),
              json.dumps({"instances": {str(k): v for k, v in gc["names"].items()},
                          "nets": gc["netmap"]}, indent=1))

    with stage("W4", "warm-up: cell models from the Liberty file"):
        cells = sorted(set(re.findall(r"sky130_fd_sc_hd__[a-z0-9_]+",
                                      open(net).read() + open(WARMUP_NET).read())))
        models = emit_models(lib, cells, os.path.join(WOUT, "03_cell_models.v"))
        say(f"{len(cells)} cell models generated from "
            f"{os.path.basename(LIB)}")

    g = Gates(net, lib)
    with stage("W5", "warm-up: simulate golden and extracted side by side"):
        if not use_iverilog:
            say("skipped (--no-iverilog)")
        else:
            tb = write(os.path.join(WOUT, "_tb_warmup.v"), TB_WARMUP)
            out, err = iverilog([models, WARMUP_NET, net, tb], "warmup", WOUT)
            os.remove(tb)
            if err:
                say("iverilog failed"), say(err.strip()[:400])
            else:
                for line in out.strip().splitlines():
                    if any(k in line for k in ("mismatch", "PASSED", "phase", "->", "WRONG")):
                        say(line.strip())
                write(os.path.join(WOUT, "05_equivalence.txt"),
                      "GOLDEN NETLIST vs NETLIST EXTRACTED FROM THE GDS\n"
                      + "=" * 70 + "\n\n" + out)

    with stage("W6", "warm-up: solve it from the extracted gates alone (SAT)"):
        keep = cone_of(g, [g.idx["S"]])
        L = ["SOLVING THE WARM-UP FROM ITS EXTRACTED GATES", "=" * 70, "",
             "No hand tracing and no reading of 00_source.v. The gates are unrolled",
             "over K clock edges, Tseitin encoded, and asked one question: is there",
             "an input sequence that drives S high?", ""]
        cnf, lit, invars, netf = unroll(
            g, 12, ["A", "B"], {"rst_n": 1, "en": 1, "clk": 1}, cone=keep)
        target = {K: netf(K + 1, g.idx["S"]) for K in range(6, 12)}
        s = solver(cnf)
        L += [f"  one unrolling to 11 edges: {cnf.n} variables, "
              f"{len(cnf.cls)} clauses", ""]
        got = None
        for K in range(6, 12):
            ok = s.solve(assumptions=[target[K]])
            m = set(s.get_model()) if ok else None
            L.append(f"  K = {K:2d} edges   {'SAT' if ok else 'UNSAT'}")
            if ok and got is None:
                bits = {p: "".join("1" if invars[p][t] in m else "0"
                                   for t in sorted(invars[p])[:8]) for p in ("A", "B")}
                got = (K, bits)
                break
        s.delete()
        K, bits = got
        a, b = int(bits["A"], 2), int(bits["B"], 2)
        say(f"minimum depth {K} edges")
        say(f"A = {bits['A']} = {a},  B = {bits['B']} = {b},  A + B = {a + b}")
        L += ["", f"minimum depth      {K} clock edges",
              f"A, first 8 edges   {bits['A']} = {a}",
              f"B, first 8 edges   {bits['B']} = {b}",
              f"A + B              {a + b}", "",
              "496 is the third perfect number: 1+2+4+8+16+31+62+124+248 = 496.",
              "A and B are eight bits each, so A + B = 496 has exactly "
              f"{sum(1 for x in range(256) if 0 <= 496 - x < 256)} solutions,",
              "and the solver is free to return any one of them.", ""]
        write(os.path.join(WOUT, "06_sat_solve.txt"), "\n".join(L))
    return {"inv": inv, "ex": ex, "gc": gc}


def do_puzzle(lib, use_iverilog):
    os.makedirs(POUT, exist_ok=True)
    R = {}

    with stage("P1", "puzzle: inventory puzzle.gds"):
        inv = inventory(PUZZLE_GDS, os.path.join(POUT, "01_gds_inventory.txt"))
        bb = inv["bbox"]
        say(f"top cell {inv['top']}, die ({bb[0][0]:.1f}, {bb[0][1]:.1f}) .. "
            f"({bb[1][0]:.1f}, {bb[1][1]:.1f}) um")
        say(f"{inv['placements']} placements: {inv['logic']} logic in "
            f"{inv['types']} types, {inv['via']} vias, {inv['phys']} physical, "
            f"{inv['diode']} diodes, {inv['odd']} not standard cells")
        say(f"ports {sorted(inv['labels'])}")
        R["inv"] = inv

    with stage("P2", "puzzle: extract a netlist from the polygons"):
        net, ex = extract(PUZZLE_GDS, POUT, "02_extracted_netlist.v")
        for nm, sh, isl in ex["layers"]:
            say(f"{nm:5s} {sh:6d} shapes -> {isl:5d} islands")
        for k in ("mcon", "via", "via2", "via3", "via4"):
            if ex["cuts"][k]:
                say(f"cut {k:5s} {ex['bridged'][k]:6d}/{ex['cuts'][k]:<6d} bridged "
                    f"metal on both sides")
        say(f"{ex['nets']} nets, {ex['logic']} logic cells, "
            f"{ex['diodes']} diodes treated as bridges")
        say(f"nets with a driver count other than one: {len(ex['bad'])}, "
            f"undriven signal nets: {len(ex['undriven'])}")
        R["ex"] = ex

    with stage("P3", "puzzle: cell models for this design's cell set"):
        cells = sorted(set(re.findall(r"sky130_fd_sc_hd__[a-z0-9_]+", open(net).read())))
        models = emit_models(lib, cells, os.path.join(POUT, "03_cell_models.v"))
        say(f"{len(cells)} cell models generated from the Liberty")
        g = Gates(net, lib)
        say(f"bit-parallel simulator: {len(g.names)} nets, {len(g.comb)} gate "
            f"outputs, {len(g.flops)} flops, {g.lines} generated lines")

    with stage("P4", "puzzle: replay the recorded silicon waveform"):
        checks, mism, edges = vcd_replay(g, PUZZLE_VCD,
                                         os.path.join(POUT, "04_vcd_replay.txt"))
        say(f"{edges} rising edges replayed, {checks} outputs compared, "
            f"{mism} mismatches")
        if mism:
            raise SystemExit("extraction does not match the recorded chip. Stop.")
        say(f"clock roots {sorted(g.clock_tree())}")
        R["replay"] = (checks, mism, edges)

    with stage("P5", "puzzle: register graph and feedback groups"):
        st = structure(g, os.path.join(POUT, "05_register_structure.txt"))
        say(f"{len(g.flops)} flops, {len(st['sccs'])} feedback groups, "
            f"{len(st['pairs'])} of them two-bit pairs")
        say(f"success is one latched flop, {', '.join(st['succ_ff'])}, whose set "
            f"condition is a wide AND tree over the pairs")
        R["st"] = st

    with stage("P6", "puzzle: falsify the rows-and-columns hypothesis"):
        cand, more = star_battle({}, limit=25, regions=False)
        succ, obytes, _, _ = run_grids(g, cand, tail=40)
        acc = bin(succ).count("1")
        msgs = collections.Counter(decode_stream(obytes, k) for k in range(len(cand)))
        say(f"{len(cand)} grids satisfying two per row, two per column, no touching")
        say(f"accepted by the netlist: {acc}")
        say(f"what the chip said instead: {dict(msgs)}")
        R["falsify"] = (len(cand), acc, dict(msgs))

    with stage("P7", "puzzle: read the region map out of the gates, 121 probes"):
        reg = probe_regions(g, st["pairs"],
                            os.path.join(POUT, "06_region_map.txt"), PUZZLE_GDS)
        say(f"column counters {len(reg['cols'])}, irregular groups "
            f"{len(reg['other'])}, shared row counters {len(reg['rows'])}")
        say(f"region sizes {reg['sizes']}, sum {sum(reg['sizes'].values())}")
        R["reg"] = reg

    with stage("P8", "puzzle: solve the gates and prove the key unique (SAT)"):
        nlin, bad = linearity(g)
        say(f"GF(2) linearity of the frame's state update: {bad} of {nlin} random "
            f"predictions failed, so it is {'not linear' if bad else 'linear'}")
        keep = cone_of(g, [g.idx["success"]])
        L = ["GATE-EXACT SAT ON THE RECOVERED NETLIST", "=" * 70, "",
             "121 input bits is 2^121 possibilities, so a sweep is not an option.",
             "A linear state update would be: if F were linear over GF(2) the chip",
             "would be an LFSR or a CRC and Gaussian elimination would invert it.",
             "Testing F(u xor v) = F(u) xor F(v) xor F(0) on random input frames:",
             f"  {bad} of {nlin} predictions failed, so F is nonlinear.", "",
             "SAT then. The netlist is unrolled over K clock edges, every gate Tseitin",
             "encoded from the same Liberty functions the simulator uses, and one",
             "clause added: success = 1.", "",
             f"cone of influence of success: {len(keep)} of {len(g.names)} nets.",
             "The output generator drops out here, which is why this is cheap.", ""]
        t = time.time()
        cnf, lit, invars, netf = unroll(
            g, FRAME + 2, ["I"], {"rst_n": 1, "enable": 1, "clk": 1}, cone=keep)
        target = {K: netf(K + 1, g.idx["success"]) for K in (FRAME, FRAME + 1)}
        say(f"one unrolling to {FRAME + 1} edges: {cnf.n} variables, "
            f"{len(cnf.cls)} clauses, {time.time() - t:.2f}s to encode")
        say(f"{cnf.folded} gates folded to a literal, {cnf.shared} shared with an "
            f"identical gate already encoded")
        L += [f"  one unrolling to {FRAME + 1} edges   {cnf.n} variables   "
              f"{len(cnf.cls)} clauses",
              f"  {cnf.folded} gates folded to a literal, {cnf.shared} shared",
              "  A K-edge question is that same formula with the success literal",
              "  asserted one step earlier, so the shorter depth needs no re-encoding.",
              ""]
        sv = solver(cnf)
        found = None
        for K in (FRAME, FRAME + 1):
            t = time.time()
            ok = sv.solve(assumptions=[target[K]])
            m = set(sv.get_model()) if ok else None
            say(f"K = {K} edges: {'SAT' if ok else 'UNSAT'}  ({time.time()-t:.2f}s)")
            L.append(f"  K = {K} edges   {'SAT' if ok else 'UNSAT'}")
            if ok:
                key = "".join("1" if invars["I"][t] in m else "0"
                              for t in sorted(invars["I"])[:FRAME])
                found = (K, key)
                break
        K, key = found
        block = [-invars["I"][t] if invars["I"][t] in m else invars["I"][t]
                 for t in sorted(invars["I"])[:FRAME]]
        sv.add_clause(block)
        ok2 = sv.solve(assumptions=[target[K]])
        sv.delete()
        say(f"blocking that assignment and re-solving: {'SAT' if ok2 else 'UNSAT'}"
            f"  -> the key is {'not unique' if ok2 else 'unique'}")
        L += ["",
              f"minimum depth      {K} clock edges. At {K-1} the netlist provably",
              "                   cannot be satisfied, so 121 cells in and the",
              "                   verdict on the next edge is exactly the protocol.",
              f"key                {key}",
              f"blocking clause    re-solve is {'SAT' if ok2 else 'UNSAT'}, so the "
              f"input is {'not unique' if ok2 else 'unique'}", "",
              "121 = 11 x 11. Laid out as a square:", ""]
        for r in range(N):
            L.append("   " + " ".join("*" if key[r * N + c] == "1" else "."
                                      for c in range(N)))
        L += ["", "Exactly two stars in every row, exactly two in every column, and",
              "no two touching, diagonals included. That is a Star Battle grid.", ""]
        write(os.path.join(POUT, "07_sat_proof.txt"), "\n".join(L))
        R["sat"] = {"K": K, "key": key, "unique": not ok2,
                    "vars": cnf.n, "clauses": len(cnf.cls), "cone": len(keep),
                    "folded": cnf.folded, "shared": cnf.shared}

    with stage("P9", "puzzle: independent solve of the recovered puzzle (z3)"):
        sols, more = star_battle(reg["label"])
        say(f"solutions to the probed constraint set: {len(sols)}"
            f"{' (and more)' if more else ' (that is all of them)'}")
        say(f"matches the SAT key: {bool(sols) and sols[0] == key}")
        R["z3"] = {"n": len(sols), "match": bool(sols) and sols[0] == key}
        sol = sols[0]

    with stage("P10", "puzzle: enumerate every string the chip can print (SAT)"):
        rows, nq = catalogue(g, reg["label"],
                             os.path.join(POUT, "10_message_catalogue.txt"))
        for msg, s, bits, p in rows:
            say(f"{msg!r:18s} success={s}  {p['stars']:3d} stars  "
                f"rows2={p['rows2']!s:5s} cols2={p['cols2']!s:5s} "
                f"regions2={p['regions2']!s:5s} touching={p['touching']}")
        say(f"{nq} SAT queries, the last one UNSAT: the catalogue is complete")
        msg = next(m for m, s, b, p in rows if s)
        R["cat"] = rows

    with stage("P11", "puzzle: emit behavioural RTL and prove it equivalent"):
        hard = touching_grids(reg["label"], 24)
        say(f"{len(hard)} grids that satisfy every count but touch, from z3, added "
            f"to the vector set")
        rtl = os.path.join(POUT, "08_recovered_rtl.v")
        tb = os.path.join(POUT, "_tb_equiv.v")
        emit_rtl(reg["label"], sol, hard, rtl, tb, g.top)
        say(f"wrote {os.path.relpath(rtl, ROOT)}")
        if not use_iverilog:
            say("equivalence run skipped (--no-iverilog)")
        else:
            out, err = iverilog([models, net, rtl, tb], "equiv", POUT,
                                shards=SHARDS)
            if err:
                say("iverilog failed"), say(err.strip()[:400])
            else:
                mism = mism_o = ngrids = 0
                lines = []
                for line in out.splitlines():
                    if line.startswith("PARTIAL"):
                        a, b, c = (int(x) for x in line.split()[1:4])
                        mism, mism_o, ngrids = mism + a, mism_o + b, ngrids + c
                    elif line.strip():
                        lines.append(line)
                lines.append(f"EQUIVALENCE: {mism} success mismatches, "
                             f"{mism_o} O mismatches over {ngrids} grids")
                lines.append(
                    "RESULT: the recovered RTL is cycle-equivalent to the "
                    "extracted netlist" if not (mism or mism_o)
                    else "RESULT: NOT equivalent")
                out = "\n".join(lines) + "\n"
                for line in out.strip().splitlines():
                    if "EQUIVALENCE" in line or "RESULT" in line or "MISMATCH" in line:
                        say(line.strip())
                write(os.path.join(POUT, "09_equivalence.txt"),
                      "THE EXTRACTED GATES vs THE RECOVERED RTL\n" + "=" * 70 + "\n\n"
                      "Two independent descriptions, two independent simulators, one\n"
                      "vector set: the unique solution, an empty grid, a full grid,\n"
                      "one-star near misses, random sparse grids, two-per-row grids,\n"
                      "two-per-row-and-column permutation pairs, and 24 grids that get\n"
                      "every count right and only break the no-touch rule. That last\n"
                      "class is what distinguishes a four-message reading of the output\n"
                      "generator from the five-message one. Every cycle of success and\n"
                      "of O[7:0] is compared.\n\n" + out)
        os.remove(tb)

    with stage("P12", "puzzle: drive the answer in and read O[7:0]"):
        succ, obytes, _, _ = run_grids(g, [sol], tail=40)
        answer = per_cycle(obytes, 0)
        msg = decode_stream(obytes, 0)
        first = next((j for j, v in enumerate(answer) if v), 0)
        succ_edge = FRAME + first
        say(f"success={succ & 1}, O[7:0] spells {msg!r}")
        say(f"success rises on enabled rising edge {succ_edge}, "
            f"{len(msg)} characters follow, one per clock")
        s1, o1, _, _ = run_grids(g, [sol], tail=40, xinit=1)
        say(f"same run with the four un-reset flops powered up high: "
            f"success={s1 & 1}, {decode_stream(o1, 0)!r}")
        R["msg"] = msg
        R["xinit_ok"] = (s1 & 1) == 1 and decode_stream(o1, 0) == msg

    with stage("P13", "puzzle: write the answer files and the winning waveform"):
        answer_files(reg["label"], sol, msg, succ_edge,
                     [0] * (FRAME - 1) + answer, POUT)
        vcd = os.path.join(POUT, "14_success_inputs.vcd")
        fs = make_success_vcd(g, sol, vcd)
        say(f"{os.path.relpath(vcd, ROOT)}: success first high at t={fs[1]} ps, "
            f"rising edge {fs[0]}")
        for f in ("11_solution_grid.txt", "12_input_sequence.txt",
                  "13_output_string.txt"):
            say(f"{os.path.relpath(os.path.join(POUT, f), ROOT)}")
    R["sol"] = sol
    R["succ_edge"] = succ_edge
    return R


TB_WARMUP = """`timescale 1ns/1ps
module tb_warmup;
  reg clk=0, rst_n=0, en=0, A=0, B=0;
  wire s_gold, s_ext;
  integer i, k, mism, seed, a, b;
  adder_demo          gold(.clk(clk), .rst_n(rst_n), .en(en), .A(A), .B(B), .S(s_gold));
  adder_demo_extracted ext(.clk(clk), .rst_n(rst_n), .en(en), .A(A), .B(B), .S(s_ext));
  always #5 clk = ~clk;
  task shift8; input [7:0] va; input [7:0] vb; begin
    rst_n=0; en=0; @(posedge clk); @(posedge clk); @(negedge clk); rst_n=1; en=1;
    for (i=7; i>=0; i=i-1) begin A=va[i]; B=vb[i]; @(posedge clk); @(negedge clk); end
  end endtask
  initial begin
    mism=0; seed=7;
    rst_n=0; @(posedge clk); @(negedge clk); rst_n=1; en=1;
    for (k=0; k<3000; k=k+1) begin
      A = $random(seed); B = $random(seed); en = |$random(seed);
      @(posedge clk);
      if (s_gold !== s_ext) begin
        mism=mism+1;
        if (mism<5) $display("  MISMATCH cycle %0d gold=%b ext=%b", k, s_gold, s_ext);
      end
      @(negedge clk);
    end
    $display("phase 1, 3000 random cycles: %0d mismatches", mism);
    for (k=0; k<200; k=k+1) begin
      a = {$random(seed)} % 256; b = {$random(seed)} % 256;
      shift8(a, b);
      if (s_ext !== ((a+b)==496)) begin
        mism=mism+1; $display("  WRONG A=%0d B=%0d S=%b", a, b, s_ext);
      end
    end
    $display("phase 2, 200 byte pairs: S <=> (A+B==496) holds in %0d of 200", 200-mism);
    shift8(245, 251); $display("A=245 B=251 sum=%0d -> S=%b", 245+251, s_ext);
    shift8(248, 248); $display("A=248 B=248 sum=%0d -> S=%b", 248+248, s_ext);
    shift8(100, 100); $display("A=100 B=100 sum=%0d -> S=%b", 100+100, s_ext);
    if (mism==0)
      $display("ALL CHECKS PASSED: extracted == golden, and S <=> (A+B==496)");
    $finish;
  end
endmodule
"""


def banner():
    """Versions of everything the flow depends on, printed by the flow itself.

    This used to be a separate Python process launched from RUN.sh purely to
    import the four packages and print their versions, which cost a whole extra
    interpreter start and a second import of shapely and z3. The run needs them
    imported anyway, so it reports them itself.
    """
    import shapely
    import z3
    print(f"python {sys.version.split()[0]}, gdstk {gdstk.__version__}, "
          f"shapely {shapely.__version__}, z3 {z3.get_version_string()}, "
          f"SAT back end {SAT_BACKEND}, {SHARDS} simulation shards")
    have = []
    for t in ("iverilog", "vvp"):
        try:
            r = subprocess.run([t, "-V"], capture_output=True, text=True)
            line = (r.stdout + r.stderr).splitlines()[0]
            have.append(f"{t} {line.split('version')[-1].split()[0]}")
        except (OSError, IndexError):
            have.append(f"{t} MISSING, the two cross-checks will be skipped")
    print(", ".join(have))


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--only", choices=("all", "warmup", "puzzle"), default="all")
    ap.add_argument("--no-iverilog", action="store_true")
    a = ap.parse_args()

    sys.stdout = Tee(os.path.join(HERE, "run.log"))
    print("GDS to RTL: recovering Jane Street's ASIC puzzle from its layout")
    print(f"repository {ROOT}")
    banner()
    with stage("P0", "load the sky130 Liberty"):
        lib = liberty(LIB)
        seq = [c for c, d in lib.items() if d["ff"]]
        say(f"{len(lib)} cells, {len(seq)} sequential, from "
            f"{os.path.relpath(LIB, ROOT)}")

    if a.only in ("all", "warmup"):
        do_warmup(lib, not a.no_iverilog)
    if a.only in ("all", "puzzle"):
        R = do_puzzle(lib, not a.no_iverilog)
        print("\n" + "=" * 72)
        print(f"ANSWER  {R['msg']}")
        print(f"KEY     {R['sol']}")
        print(f"success on enabled rising edge {R['succ_edge']}, "
              f"unique at the gate level: {R['sat']['unique']}")
        print("=" * 72)
    print(f"\ntotal {time.time() - _T0:.1f}s")


if __name__ == "__main__":
    main()
