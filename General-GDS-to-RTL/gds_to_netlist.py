#!/usr/bin/env python3
"""
gds_to_netlist.py -- point it at any sky130 GDSII layout and get a netlist back.

    python3 General-GDS-to-RTL/gds_to_netlist.py mychip.gds
    python3 General-GDS-to-RTL/gds_to_netlist.py mychip.gds -o out/
    python3 General-GDS-to-RTL/gds_to_netlist.py mychip.gds --def mychip.def
    python3 General-GDS-to-RTL/gds_to_netlist.py mychip.gds --golden golden.v
    python3 General-GDS-to-RTL/gds_to_netlist.py mychip.gds --lef X.lef --lib Y.lib

This is the puzzle pipeline's extractor with the puzzle taken out of it. It
imports GDS-to-RTL/gds_to_rtl.py rather than copying anything, so the geometry
code that runs here is the same code that was proved exact against the warm-up's
golden netlist, net for net.

What it can do for any layout:

  * inventory       every placement, orientation, label and layer in the file
  * netlist         structural Verilog recovered from polygon overlap alone
  * cell models     simulation models for the cell types the design uses,
                    generated from the Liberty file, no hand-written truth tables
  * structure       register graph, feedback groups, clock tree, and what each
                    output depends on
  * checks          one driver per net, no combinational loops, every via
                    landing on metal on both sides
  * cross-check     against a DEF, and against a golden netlist, if you have them

What it cannot do, and neither can anything else: hand you behavioural RTL that
says what the circuit is for. Synthesis threw the module boundaries, the signal
names and the intent away, and no tool gets them back. What the structure report
does is narrow where you have to look: a feedback group of size 2 is a two-bit
counter, a group of size 8 is a byte-wide register or a state machine, and the
cone of an output tells you which of them feed it.

Layer numbers are sky130's. For another PDK, pass --layers with a JSON file of
the same shape as the LAYERS constant printed by --show-layers.
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PIPELINE = os.path.join(ROOT, "GDS-to-RTL", "gds_to_rtl.py")


def load_pipeline():
    """Import the validated extractor without running it."""
    if not os.path.exists(PIPELINE):
        sys.exit(f"cannot find {PIPELINE}, run this from inside the repository")
    spec = importlib.util.spec_from_file_location("gds_to_rtl", PIPELINE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def report_structure(gr, g, path):
    """Register graph, feedback groups, clock tree and output cones.

    The one genuinely general thing to say about a flattened netlist is which
    flip-flops feed which. Build a graph over flops alone, with an edge from a to
    b when a's output reaches b's input through combinational logic, and take the
    strongly connected components. A cycle in that graph cannot be optimised away
    by any synthesiser, so the groups that come out are the design's counters,
    accumulators and state machines whatever it was written in.
    """
    combof = {o: a for o, a in g.comb}
    dof = {}
    for f in g.flops:
        for k in ("q", "qn"):
            if f[k] is not None:
                dof[f[k]] = f["inst"]

    def sources(net_ids):
        """Walk back to flop outputs and primary inputs, not through them."""
        seen, out, stack = set(), set(), list(net_ids)
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            if n in dof:
                out.add(("FF", dof[n]))
            elif g.names[n] in g.ports and g.ports[g.names[n]] == "input":
                out.add(("PORT", g.names[n]))
            elif n in combof:
                stack += list(gr.ast_nets(combof[n], set()))
        return out

    edges = {}
    for f in g.flops:
        feed = [a for a in (f["d"], f["clr"], f["pre"]) if a is not None]
        nets = set()
        for a in feed:
            nets |= gr.ast_nets(a, set())
        edges[f["inst"]] = sources(nets)

    order = {f["inst"]: i for i, f in enumerate(g.flops)}
    index, low, onstk, stk, comps, counter = {}, {}, set(), [], [], [0]

    def strongconnect(root):
        work = [(root, iter(sorted((nm for k, nm in edges.get(root, ())
                                    if k == "FF"), key=order.get)))]
        index[root] = low[root] = counter[0]
        counter[0] += 1
        stk.append(root)
        onstk.add(root)
        while work:
            v, it = work[-1]
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter[0]
                    counter[0] += 1
                    stk.append(w)
                    onstk.add(w)
                    work.append((w, iter(sorted((nm for k, nm in edges.get(w, ())
                                                 if k == "FF"), key=order.get))))
                    break
                if w in onstk:
                    low[v] = min(low[v], index[w])
            else:
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
                    comps.append(sorted(comp, key=order.get))

    for f in g.flops:
        if f["inst"] not in index:
            strongconnect(f["inst"])

    sccs = sorted((c for c in comps if len(c) > 1),
                  key=lambda c: (-len(c), order[c[0]]))
    sizes = collections.Counter(len(c) for c in sccs)

    L = ["REGISTER-LEVEL STRUCTURE", "=" * 70, "",
         f"module           {g.top}",
         f"logic cells      {len(g.cellof)}",
         f"nets             {len(g.names)}",
         f"flip-flops       {len(g.flops)}  "
         f"{dict(collections.Counter(g.cellof[f['inst']] for f in g.flops))}",
         f"clock roots      {sorted(g.clock_tree())}",
         f"primary inputs   {g.inputs}",
         f"primary outputs  {g.outputs}",
         f"feedback groups  {len(sccs)}"]
    for n in sorted(sizes, reverse=True):
        L.append(f"  of size {n:<3d}    {sizes[n]}")
    L += ["", "A group of size 2 is almost always a two-bit counter. A larger",
          "group is a wider counter, an accumulator or a state machine. A flop in",
          "no group at all is a pipeline stage or a latched flag.", "",
          "FEEDBACK GROUPS (Tarjan SCC over the register graph)", "-" * 70]
    for c in sccs:
        ext = sorted({nm for f in c for kind, nm in edges[f] if kind == "PORT"})
        L.append(f"  size {len(c):2d}  external inputs {ext or 'none'}")
        L.append(f"           {' '.join(c)}")
    L += ["", "WHAT EACH OUTPUT DEPENDS ON", "-" * 70]
    for o in g.outputs:
        s = sources([g.idx[o]])
        ffs = sorted(nm for k, nm in s if k == "FF")
        L.append(f"  {o:12s} {len(ffs):3d} flip-flops, "
                 f"ports {sorted(nm for k, nm in s if k == 'PORT')}")
        L.append(f"               {' '.join(ffs) if ffs else '(combinational only)'}")
    L.append("")
    return gr.write(path, "\n".join(L)), {"sccs": len(sccs), "sizes": dict(sizes)}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__.strip().splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gds", nargs="?", help="the GDSII file to read")
    ap.add_argument("-o", "--out", default="recovered",
                    help="output directory, default recovered/")
    ap.add_argument("--lef", help="merged LEF, default the sky130 one in pdk/")
    ap.add_argument("--lib", help="Liberty file, default the sky130 one in pdk/")
    ap.add_argument("--def", dest="deffile",
                    help="a DEF to match placements against, if you have one")
    ap.add_argument("--golden",
                    help="a golden gate netlist to compare the net partition with")
    ap.add_argument("--layers", help="JSON layer table, for a non-sky130 PDK")
    ap.add_argument("--show-layers", action="store_true",
                    help="print the layer table this build uses and exit")
    a = ap.parse_args()

    gr = load_pipeline()

    if a.show_layers:
        print(json.dumps({"conductor": gr.CONDUCTOR, "names": gr.LNAME,
                          "cuts": gr.CUTNAME, "gap_um": gr.GAP}, indent=2))
        return
    if not a.gds:
        ap.error("give me a .gds file, or --show-layers")

    if a.layers:
        t = json.load(open(a.layers))
        gr.CONDUCTOR = [int(x) for x in t["conductor"]]
        gr.LNAME = {int(k): v for k, v in t["names"].items()}
        gr.CUTNAME = {int(k): v for k, v in t["cuts"].items()}
        gr.GAP = float(t.get("gap_um", gr.GAP))
    if a.lef:
        gr.LEF = os.path.abspath(a.lef)
    if a.lib:
        gr.LIB = os.path.abspath(a.lib)
    for f in (gr.LEF, gr.LIB):
        if not os.path.exists(f):
            sys.exit(f"missing PDK file {f}, pass --lef and --lib")

    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    stem = os.path.splitext(os.path.basename(a.gds))[0]
    print(f"reading {a.gds}")
    print(f"writing {out}/")

    with gr.stage("G0", "load the Liberty file"):
        lib = gr.liberty(gr.LIB)
        gr.say(f"{len(lib)} cells, "
               f"{len([1 for d in lib.values() if d['ff']])} sequential")

    with gr.stage("G1", "inventory the GDS"):
        inv = gr.inventory(a.gds, os.path.join(out, f"{stem}_01_inventory.txt"))
        bb = inv["bbox"]
        gr.say(f"top cell {inv['top']}, die ({bb[0][0]:.2f}, {bb[0][1]:.2f}) .. "
               f"({bb[1][0]:.2f}, {bb[1][1]:.2f}) um")
        gr.say(f"{inv['placements']} placements: {inv['logic']} logic in "
               f"{inv['types']} types, {inv['via']} vias, {inv['phys']} physical, "
               f"{inv['diode']} diodes, {inv['odd']} not standard cells")
        gr.say(f"top-level labels {sorted(inv['labels'])}")
        if inv["odd"]:
            gr.say(f"{inv['odd']} placements are not standard cells. In this "
                   f"puzzle that was where an easter egg was hidden")

    with gr.stage("G2", "extract a netlist from the polygons"):
        net, ex = gr.extract(a.gds, out, f"{stem}_02_netlist.v")
        for nm, sh, isl in ex["layers"]:
            gr.say(f"{nm:5s} {sh:6d} shapes -> {isl:5d} conductors")
        for k, n in ex["cuts"].items():
            gr.say(f"cut {k:5s} {ex['bridged'][k]:6d}/{n:<6d} landed on metal "
                   f"on both sides")
        gr.say(f"{ex['nets']} nets, {ex['logic']} logic cells, "
               f"{ex['diodes']} antenna diodes treated as bridges")
        gr.say(f"nets with a driver count other than one: {len(ex['bad'])}, "
               f"undriven signal nets: {len(ex['undriven'])}")
        if ex["bad"]:
            gr.say("WARNING: a net with no driver, or with two, means one real "
                   "connection was missed or one was invented")

    with gr.stage("G3", "cell models and the simulator"):
        import re
        cells = sorted(set(re.findall(r"[A-Za-z0-9_]+__[a-z0-9_]+", open(net).read())))
        cells = [c for c in cells if c in lib]
        gr.emit_models(lib, cells, os.path.join(out, f"{stem}_03_cell_models.v"))
        gr.say(f"{len(cells)} cell models generated from the Liberty")
        g = gr.Gates(net, lib)
        gr.say(f"bit-parallel simulator: {len(g.names)} nets, {len(g.comb)} gate "
               f"outputs, {len(g.flops)} flops, {g.lines} generated lines")
        gr.say(f"combinational loops: 0 (the topological sort completed)")

    with gr.stage("G4", "register structure"):
        _, st = report_structure(
            gr, g, os.path.join(out, f"{stem}_04_structure.txt"))
        gr.say(f"{len(g.flops)} flops in {st['sccs']} feedback groups, "
               f"sizes {st['sizes']}")
        gr.say(f"clock roots {sorted(g.clock_tree())}")

    if a.deffile and a.golden:
        with gr.stage("G5", "cross-check against the DEF and the golden netlist"):
            res = gr.golden_check(a.gds, a.deffile, a.golden, ex,
                                  os.path.join(out, f"{stem}_05_crosscheck.txt"))
            gr.say(f"placements matched to DEF components "
                   f"{res['matched']}/{res['comps']}, unmatched {res['unmatched']}")
            gr.say(f"net partition vs the golden netlist: {res['ok']} exact, "
                   f"{res['bad']} mismatches, golden has {res['gold']} nets")
            gr.say(f"instance names recovered: {len(res['names'])}")
    elif a.deffile or a.golden:
        print("\nthe cross-check needs both --def and --golden, skipping it")

    print()
    print("=" * 72)
    print(f"netlist    {net}")
    print(f"structure  {os.path.join(out, stem + '_04_structure.txt')}")
    print(f"{ex['nets']} nets, {ex['logic']} cells, {len(g.flops)} flops, "
          f"{len(ex['bad'])} nets with a driver count other than one")
    print("=" * 72)


if __name__ == "__main__":
    main()
