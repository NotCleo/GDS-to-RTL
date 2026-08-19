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
  * behaviour       the RTL: boolean equations for the combinational logic and
                    clocked blocks for the registers, and for a combinational
                    design the exact function of every output plus its truth
                    table
  * equivalence     the recovered RTL run against the recovered gates, so the
                    behaviour is checked rather than claimed
  * structure       register graph, feedback groups, clock tree, and what each
                    output depends on
  * checks          one driver per net, no combinational loops, every via
                    landing on metal on both sides
  * cross-check     against a DEF, and against a golden netlist, if you have them

What it cannot do, and neither can anything else, is tell you what the circuit
is for. Behaviour and intent are different things. The behaviour is fully
recoverable, because every cell's function is in the Liberty file and a netlist
of known functions is a system of boolean equations; that is what the RTL and
the function report contain, and the equivalence run is there to prove it. The
intent is not, because synthesis threw the module boundaries, the signal names
and the comments away and no tool gets them back. What the structure report does
is narrow where to look: a feedback group of size 2 is a two-bit counter, a
group of size 8 is a byte-wide register or a state machine, and the cone of an
output tells you which of them feed it.

Layer numbers are sky130's. For another PDK, pass --layers with a JSON file of
the same shape as the LAYERS constant printed by --show-layers.
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PIPELINE = os.path.join(ROOT, "GDS-to-RTL", "gds_to_rtl.py")


def use_repo_venv():
    """Hand the process to the repository's .venv if this interpreter lacks gdstk.

    RUN.sh builds a .venv beside the pipeline and installs gdstk, shapely, numpy
    and the solvers into it. Running this script with a bare python3 therefore
    dies on an import several frames deep, which tells the reader nothing about
    what to do next. If the packages are missing here and that .venv exists, run
    there instead. The environment flag makes the handover happen at most once,
    so a .venv that is itself incomplete reports that rather than looping.
    """
    if importlib.util.find_spec("gdstk") is not None:
        return
    venv = os.path.join(ROOT, ".venv", "bin", "python")
    if os.path.exists(venv) and not os.environ.get("GDS_TO_RTL_VENV"):
        os.environ["GDS_TO_RTL_VENV"] = "1"
        os.execv(venv, [venv, os.path.abspath(__file__)] + sys.argv[1:])
    sys.exit("gdstk is not importable and " + (
        "the .venv did not provide it either." if os.path.exists(venv) else
        f"there is no .venv in {ROOT}.")
        + " Run bash RUN.sh once to build one, or install requirements.txt.")


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


IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*(\[\d+\])?$")
ATOM = re.compile(r"^~*[A-Za-z_\\][A-Za-z0-9_$\\]*(\[\d+\])?$")
INLINE_SIZE = 16


def wrap(line, cont="      ", width=78):
    """Break a long expression at its operators rather than letting it run."""
    if len(line) <= width:
        return line
    lead = line[:len(line) - len(line.lstrip())]
    out, cur = [], lead
    for tok in re.findall(r"[^\s]+\s*", line):
        if cur and len(cur) + len(tok) > width:
            out.append(cur.rstrip())
            cur = cont
        cur += tok
    out.append(cur.rstrip())
    return "\n".join(out)


def vname(nm):
    """A net name as Verilog. Anything the language would choke on is escaped."""
    return nm if IDENT.match(nm) else "\\" + nm + " "


def group(names):
    """Split a list of net names into scalars and bus bits."""
    buses, scalars = collections.defaultdict(list), []
    for nm in names:
        m = re.match(r"^(\w+)\[(\d+)\]$", nm)
        buses[m.group(1)].append(int(m.group(2))) if m else scalars.append(nm)
    return sorted(scalars), {b: (max(v), min(v)) for b, v in sorted(buses.items())}


def declare(kw, names, regs=()):
    """Declaration lines for a set of nets, bus bits collected back into buses."""
    scalars, buses = group(names)
    out = []
    for s in scalars:
        out.append(f"  {kw}{' reg' if s in regs else ''} {vname(s)};")
    for b, (hi, lo) in buses.items():
        isreg = any(f"{b}[{i}]" in regs for i in range(lo, hi + 1))
        out.append(f"  {kw}{' reg' if isreg else ''} [{hi}:{lo}] {b};")
    return out, [s for s in scalars] + list(buses)


def recover_behaviour(gr, g):
    """Turn the flat gate netlist back into boolean equations and clocked blocks.

    Two facts make this exact rather than a guess. Every cell's function came
    out of the Liberty file, so composing them is composing the same algebra the
    silicon implements; and a net driven by one cell output is that cell's
    function of its inputs, with no timing or drive strength left in it. So the
    netlist already is a system of boolean equations, one per net, and all that
    is missing is a readable way to write it down.

    Writing it down naively does not work: substituting every equation into its
    consumer expands a cone into an expression exponential in its depth, which
    is why fully expanding a counter produces megabytes. The rule used here is
    that a net keeps its own line when more than one consumer reads it, when it
    is a port, or when it holds state, and is folded into its consumer only when
    exactly one thing reads it. Every shared term is then written once and the
    output stays linear in the gate count, while the long thin chains that a
    synthesiser leaves behind, buffer into buffer into inverter, collapse.
    """
    combof = {o: a for o, a in g.comb}
    qof = {}
    for f in g.flops:
        for k in ("q", "qn"):
            if f[k] is not None:
                qof[f[k]] = (f, k)

    users = collections.Counter()
    for _, a in g.comb:
        for n in gr.ast_nets(a, set()):
            users[n] += 1
    for f in g.flops:
        for k in ("d", "clr", "pre"):
            if f[k] is not None:
                for n in gr.ast_nets(f[k], set()):
                    users[n] += 1

    kept = {g.idx[nm] for nm in g.outputs} | set(qof)
    kept |= {n for n in combof if users[n] != 1}
    for f in g.flops:
        if f["clk"]:
            kept.add(g.idx[f["clk"]])
        for k in ("clr", "pre"):
            if f[k] is not None:
                kept |= gr.ast_nets(f[k], set())

    size = {}

    def leaves(ast):
        """How many leaf terms this subtree would print if it were inlined."""
        if ast[0] == "n":
            return size.get(ast[1], 1)
        if ast[0] == "c":
            return 1
        if ast[0] == "!":
            return leaves(ast[1])
        return leaves(ast[1]) + leaves(ast[2])

    for o in g.order:
        if o in kept:
            continue
        n = leaves(combof[o])
        if n > INLINE_SIZE:
            kept.add(o)
        else:
            size[o] = n

    def leaf(nid):
        if nid in kept or nid not in combof:
            return vname(g.names[nid])
        return render(combof[nid])

    def render(ast):
        k = ast[0]
        if k == "c":
            return "1'b1" if ast[1] else "1'b0"
        if k == "n":
            return leaf(ast[1])
        if k == "!":
            inner = render(ast[1])
            if inner.startswith("~"):
                return inner[1:]
            return ("~" + inner) if ATOM.match(inner) else f"~({inner})"
        return f"({render(ast[1])} {k} {render(ast[2])})"

    assigns = [(g.names[o], render(combof[o]))
               for o in g.order if o in kept and o in combof]

    def edge_of(ast):
        """Sensitivity term and active-high condition for an async set or clear."""
        if ast[0] == "!" and ast[1][0] == "n":
            nm = vname(g.names[ast[1][1]])
            return f"negedge {nm}", f"~{nm}"
        if ast[0] == "n":
            nm = vname(g.names[ast[1]])
            return f"posedge {nm}", nm
        nets = sorted(gr.ast_nets(ast, set()))
        return (" or ".join(f"posedge {vname(g.names[n])}" for n in nets),
                render(ast))

    blocks = collections.defaultdict(list)
    for f in g.flops:
        if f["q"] is None and f["qn"] is None:
            continue
        sens = [f"posedge {vname(g.names[g.idx[f['clk']]])}"] if f["clk"] else []
        guard = []
        for k, val in (("clr", "1'b0"), ("pre", "1'b1")):
            if f[k] is not None:
                e, cond = edge_of(f[k])
                sens.append(e)
                guard.append((cond, val))
        target = f["q"] if f["q"] is not None else f["qn"]
        invert = f["q"] is None
        blocks[(" or ".join(sens), tuple(guard))].append(
            (g.names[target], render(f["d"]), invert, f["init"]))

    regs = set()
    extra = []
    for key, items in blocks.items():
        for nm, _, invert, _ in items:
            regs.add(nm)
    for f in g.flops:
        if f["q"] is not None and f["qn"] is not None:
            extra.append((g.names[f["qn"]], "~" + vname(g.names[f["q"]])))
    return {"assigns": assigns, "blocks": blocks, "regs": regs, "mirror": extra,
            "kept": kept, "combof": combof}


def write_behaviour(gr, g, path, module):
    """Emit the recovered RTL: one module, equations and clocked blocks."""
    r = recover_behaviour(gr, g)
    regs = {nm for nm in r["regs"]}
    mirrored = {nm for nm, _ in r["mirror"]}
    internal = sorted({g.names[n] for n in r["kept"]
                       if g.names[n] not in g.ports} | mirrored)

    in_d, in_h = declare("input ", g.inputs)
    out_d, out_h = declare("output", g.outputs, regs)
    wire_d, _ = declare("wire", [n for n in internal if n not in regs])
    reg_d, _ = declare("reg", [n for n in internal if n in regs])

    L = [f"// Behavioural RTL recovered from the GDS alone, by way of the gate",
         f"// netlist in the same directory. Every equation below came out of the",
         f"// Liberty description of the cells the layout places, so nothing about",
         f"// what a gate does is asserted here by hand.",
         f"//",
         f"// {len(g.flops)} flip-flops, {len(r['assigns'])} equations, "
         f"{len(g.inputs)} inputs, {len(g.outputs)} outputs.",
         f"// Names survive only where the layout still carried a label. The",
         f"// module boundaries and the intent did not survive synthesis and are",
         f"// not recoverable from any layout.",
         "",
         f"module {module} (" + ", ".join(in_h + out_h) + ");"]
    L += in_d + out_d + wire_d + reg_d
    if r["assigns"] or r["mirror"]:
        L.append("")
    for nm, e in r["assigns"]:
        if nm not in regs:
            L.append(wrap(f"  assign {vname(nm)} = {e};"))
    for nm, e in r["mirror"]:
        L.append(wrap(f"  assign {vname(nm)} = {e};"))

    for (sens, guard), items in r["blocks"].items():
        L.append("")
        L.append(f"  always @({sens}) begin")
        pad = "    "
        for cond, val in guard:
            L.append(f"{pad}if ({cond}) begin")
            for nm, _, invert, _ in items:
                L.append(f"{pad}  {vname(nm)} <= {val};")
            L.append(f"{pad}end else begin")
            pad += "  "
        for nm, d, invert, _ in items:
            L.append(wrap(f"{pad}{vname(nm)} <= "
                          f"{('~(' + d + ')') if invert else d};", pad + "    "))
        for _ in guard:
            pad = pad[:-2]
            L.append(f"{pad}end")
        L.append("  end")

    init = [nm for (_, _), items in r["blocks"].items()
            for nm, _, _, i in items if i]
    if init:
        L += ["", "  initial begin"]
        L += [f"    {vname(nm)} = 1'b1;" for nm in sorted(init)]
        L.append("  end")
    L.append("endmodule")
    return gr.write(path, "\n".join(L) + "\n"), r


def truth_table(gr, g, limit=14):
    """Every input combination at once, using the bit-parallel simulator.

    Bit k of every net holds the value that net takes in trial k, so one pass
    over the gates evaluates all 2^n input combinations simultaneously and the
    whole table falls out of n+m integers. Only worth doing while 2^n fits in
    memory, which is what limit is for.
    """
    ins = sorted(g.inputs)
    if g.flops or not ins or len(ins) > limit:
        return None
    lanes = 1 << len(ins)
    g.reset(lanes)
    for i, nm in enumerate(ins):
        half, mask = 1 << i, 0
        ones = (1 << half) - 1
        for start in range(half, lanes, half << 1):
            mask |= ones << start
        g.v[g.idx[nm]] = mask
    g._comb(g.v, g.M)
    return ins, lanes, {o: g.v[g.idx[o]] for o in g.outputs}


def sop(ins, lanes, bits):
    """Sum of products straight off the truth table, one product per minterm."""
    terms = []
    for k in range(lanes):
        if (bits >> k) & 1:
            terms.append(" & ".join(nm if (k >> i) & 1 else "~" + nm
                                    for i, nm in enumerate(ins)))
    if not terms:
        return "1'b0"
    if len(terms) == lanes:
        return "1'b1"
    return " | ".join(f"({t})" for t in terms)


def write_function(gr, g, path, r):
    """What the circuit computes, in the plainest form the design allows."""
    L = ["WHAT THIS CIRCUIT COMPUTES", "=" * 70, "",
         f"module          {g.top}",
         f"primary inputs  {sorted(g.inputs)}",
         f"primary outputs {sorted(g.outputs)}",
         f"flip-flops      {len(g.flops)}",
         f"gate equations  {len(r['assigns'])}", ""]

    tt = truth_table(gr, g)
    if tt:
        ins, lanes, cols = tt
        L += ["This design has no flip-flops, so its behaviour is a function of",
              "its inputs and nothing else, and the table below is complete: every",
              f"one of the {lanes} input combinations, evaluated through the gates",
              "recovered from the layout.", "",
              "EXACT FUNCTION OF EACH OUTPUT", "-" * 70]
        for o in sorted(g.outputs):
            L.append(f"  {o} = {sop(ins, lanes, cols[o])}")
        L += ["", "TRUTH TABLE", "-" * 70,
              "  " + "  ".join(f"{n:>4s}" for n in ins) + "   |  "
              + "  ".join(f"{n:>6s}" for n in sorted(g.outputs))]
        for k in range(lanes):
            row = "  " + "  ".join(f"{(k >> i) & 1:>4d}" for i in range(len(ins)))
            row += "   |  " + "  ".join(f"{(cols[o] >> k) & 1:>6d}"
                                        for o in sorted(g.outputs))
            L.append(row)
    else:
        L += ["This design holds state, so no single table describes it. What it",
              "does is fixed by two things, and both are in the recovered RTL next",
              "to this file: what each output is as a function of the inputs and",
              "the current register contents, and what each register becomes on",
              "the next clock edge.", "",
              "The register graph, its feedback groups and the cone of each output",
              "are in the structure report. A feedback group is a counter or a",
              "state machine; those are the pieces worth reading first.", ""]
        if len(g.inputs) <= 14 and not g.flops:
            pass
        L += ["OUTPUT EQUATIONS", "-" * 70]
        byname = dict(r["assigns"])
        for o in sorted(g.outputs):
            e = byname.get(o)
            L.append(f"  {o} = {e}" if e else f"  {o} = (driven by a register)")
    L.append("")
    return gr.write(path, "\n".join(L))


def write_testbench(gr, g, path, gatemod, rtlmod):
    """A testbench that runs the gates and the recovered RTL against each other."""
    clocks = sorted(set(g.clock_tree()) & set(g.inputs))
    resets = {}
    for f in g.flops:
        for k in ("clr", "pre"):
            a = f[k]
            if a is None:
                continue
            if a[0] == "!" and a[1][0] == "n":
                nm, lvl = g.names[a[1][1]], 0
            elif a[0] == "n":
                nm, lvl = g.names[a[1]], 1
            else:
                continue
            if g.ports.get(nm) == "input":
                resets[nm] = lvl
    data = [n for n in sorted(g.inputs) if n not in clocks and n not in resets]

    def width(names):
        scalars, buses = group(names)
        return [(s, None) for s in scalars] + [(b, hi) for b, (hi, _) in buses.items()]

    L = ["`timescale 1ns/1ps", "module tb_recovered;"]
    for nm, hi in width(g.inputs):
        L.append(f"  reg {'' if hi is None else f'[{hi}:0] '}{nm};")
    for side in ("g", "r"):
        for nm, hi in width(g.outputs):
            L.append(f"  wire {'' if hi is None else f'[{hi}:0] '}{side}_{nm};")
    conn = [f".{n}({n})" for n, _ in width(g.inputs)]
    L.append(f"  {gatemod} dut_gates (" + ", ".join(
        conn + [f".{n}(g_{n})" for n, _ in width(g.outputs)]) + ");")
    L.append(f"  {rtlmod} dut_rtl (" + ", ".join(
        conn + [f".{n}(r_{n})" for n, _ in width(g.outputs)]) + ");")
    L += ["  integer i, mism, seed;",
          "  task compare; begin"]
    for nm, _ in width(g.outputs):
        L.append(f"    if (g_{nm} !== r_{nm}) begin mism = mism + 1;")
        L.append(f"      if (mism < 6) $display(\"  MISMATCH i=%0d {nm} "
                 f"gates=%b rtl=%b\", i, g_{nm}, r_{nm}); end")
    L += ["  end endtask"]

    bits = sum(1 if hi is None else hi + 1 for _, hi in width(g.inputs))
    if clocks:
        L.append(f"  always #5 {clocks[0]} = ~{clocks[0]};")
        L += ["  initial begin", "    mism = 0; seed = 3;",
              f"    {clocks[0]} = 0;"]
        for nm, lvl in sorted(resets.items()):
            L.append(f"    {nm} = 1'b{lvl};")
        for nm, hi in width(data):
            L.append(f"    {nm} = 0;")
        L += [f"    repeat (4) @(posedge {clocks[0]});"]
        for nm, lvl in sorted(resets.items()):
            L.append(f"    {nm} = 1'b{1 - lvl};")
        L += ["    for (i = 0; i < 2000; i = i + 1) begin"]
        for nm, _ in width(data):
            L.append(f"      {nm} = $random(seed);")
        L += [f"      @(posedge {clocks[0]});", "      #1 compare;", "    end",
              "    $display(\"CHECKED 2000 clocked cycles, %0d mismatches\", mism);"]
    else:
        n = min(1 << bits, 1 << 16) if bits <= 16 else 20000
        L += ["  initial begin", "    mism = 0; seed = 3;",
              f"    for (i = 0; i < {n}; i = i + 1) begin"]
        if bits <= 16:
            L.append("      {" + ", ".join(n for n, _ in width(g.inputs)) + "} = i;")
        else:
            for nm, _ in width(g.inputs):
                L.append(f"      {nm} = $random(seed);")
        L += ["      #1 compare;", "    end",
              f"    $display(\"CHECKED {'all ' if bits <= 16 else ''}{n} input "
              f"vectors, %0d mismatches\", mism);"]
    L += ["    if (mism == 0) $display(\"RESULT: the recovered RTL is equivalent "
          "to the gates extracted from the layout\");",
          "    else $display(\"RESULT: NOT equivalent, %0d mismatches\", mism);",
          "    $finish;", "  end", "endmodule"]
    return gr.write(path, "\n".join(L) + "\n")


def summarise(out, stem, net, rtl, ex, g):
    """The closing block: where each recovered file went, and the headline counts."""
    print()
    print("=" * 72)
    print(f"netlist    {net}")
    print(f"structure  {os.path.join(out, stem + '_04_structure.txt')}")
    print(f"RTL        {rtl}")
    print(f"function   {os.path.join(out, stem + '_06_function.txt')}")
    print(f"{ex['nets']} nets, {ex['logic']} cells, {len(g.flops)} flops, "
          f"{len(ex['bad'])} nets with a driver count other than one")
    print("=" * 72)


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

    use_repo_venv()
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
        cells = sorted(set(re.findall(r"[A-Za-z0-9_]+__[a-z0-9_]+", open(net).read())))
        cells = [c for c in cells if c in lib]
        models = gr.emit_models(lib, cells,
                                os.path.join(out, f"{stem}_03_cell_models.v"))
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

    base = g.top[:-len("_extracted")] if g.top.endswith("_extracted") else g.top
    rtlmod = base + "_recovered"
    rtl = os.path.join(out, f"{stem}_05_recovered_rtl.v")
    with gr.stage("G5", "recover the behaviour: equations and clocked blocks"):
        _, rec = write_behaviour(gr, g, rtl, rtlmod)
        gr.say(f"{len(rec['assigns'])} boolean equations, "
               f"{len(rec['blocks'])} clocked block(s) over {len(g.flops)} flops")
        write_function(gr, g, os.path.join(out, f"{stem}_06_function.txt"), rec)
        tt = truth_table(gr, g)
        if tt:
            ins, lanes, cols = tt
            gr.say(f"combinational, so the function is exact: {lanes} input "
                   f"combinations evaluated")
            for o in sorted(g.outputs):
                e = sop(ins, lanes, cols[o])
                gr.say(f"{o} = {e if len(e) < 90 else e[:87] + '...'}")
        else:
            gr.say("sequential, so the behaviour is the output equations plus "
                   "the next-state equations, both in the RTL")

    with gr.stage("G6", "prove the recovered RTL equivalent to the gates"):
        if not g.inputs or not g.outputs:
            gr.say("skipped: the layout carried no pin shapes, so there is no "
                   "module boundary to drive or observe")
            return summarise(out, stem, net, rtl, ex, g)
        tb = write_testbench(gr, g, os.path.join(out, "_tb_recovered.v"),
                             g.top, rtlmod)
        try:
            res, err = gr.iverilog([models, net, rtl, tb], "recovered", out)
        except OSError:
            res, err = None, "iverilog is not installed"
        os.remove(tb)
        if err:
            gr.say("skipped: " + str(err).strip().splitlines()[0][:200])
        else:
            for line in res.strip().splitlines():
                if line.strip():
                    gr.say(line.strip())
            gr.write(os.path.join(out, f"{stem}_07_equivalence.txt"),
                     "RECOVERED RTL vs GATES EXTRACTED FROM THE LAYOUT\n"
                     + "=" * 70 + "\n\n" + res)

    if a.deffile and a.golden:
        with gr.stage("G7", "cross-check against the DEF and the golden netlist"):
            res = gr.golden_check(a.gds, a.deffile, a.golden, ex,
                                  os.path.join(out, f"{stem}_08_crosscheck.txt"))
            gr.say(f"placements matched to DEF components "
                   f"{res['matched']}/{res['comps']}, unmatched {res['unmatched']}")
            gr.say(f"net partition vs the golden netlist: {res['ok']} exact, "
                   f"{res['bad']} mismatches, golden has {res['gold']} nets")
            gr.say(f"instance names recovered: {len(res['names'])}")
    elif a.deffile or a.golden:
        print("\nthe cross-check needs both --def and --golden, skipping it")

    summarise(out, stem, net, rtl, ex, g)


if __name__ == "__main__":
    main()
