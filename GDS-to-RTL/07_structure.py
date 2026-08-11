#!/usr/bin/env python3
"""
Register-transfer-level structure recovery from a flat gate netlist.

Gate netlists have no hierarchy: 728 cells in one bag. To understand the design
you must rebuild the *register graph* -- one node per flip-flop, an edge a->b
when Q(a) is in the combinational fan-in of D(b). That graph exposes the
architecture that synthesis flattened away:

  * a pure chain a->b->c with no other fan-in  = shift register
  * a strongly-connected component (SCC)       = a counter / FSM / accumulator
  * a flop with only external inputs feeding D = input register
  * flops whose Q reaches `success`            = the comparison logic

Usage: python 07_structure.py <netlist.v> <outdir>
"""
import sys, re, collections, json

OUT_PINS = {"X", "Y", "Q", "Q_N", "HI", "LO"}
PWR = {"VPWR", "VGND", "VPB", "VNB"}
FF = ("dfrtp", "dfstp", "dfxtp", "dfbbn", "dfrbp", "dfxbp")
FF_DATA = {"D", "SCD", "SCE", "DE"}
FF_ASYNC = {"SET_B", "RESET_B"}


def parse(path):
    txt = open(path).read()
    insts = []
    for m in re.finditer(r"(sky130_fd_sc_hd__\w+)\s+(\w+)\s*\(([^;]*)\);", txt, re.S):
        cell, name, body = m.groups()
        conns = {k: v.strip() for k, v in re.findall(r"\.(\w+)\(([^)]*)\)", body)}
        insts.append((cell, name, conns))
    ports = {}
    for m in re.finditer(r"^\s*(input|output)\s*(\[(\d+):(\d+)\])?\s*(\w+)\s*;", txt, re.M):
        kind, _, hi, lo, nm = m.groups()
        ports[nm] = (kind, (int(hi), int(lo)) if hi else None)
    return insts, ports


def main(netlist, outdir):
    insts, ports = parse(netlist)
    conns_of = {nm: c for _, nm, c in insts}
    cell_of = {nm: c.split("__")[-1] for c, nm, _ in insts}
    driver = {}
    for cell, nm, conns in insts:
        for pin, net in conns.items():
            if pin in OUT_PINS and net:
                driver[net] = nm
    flops = [nm for nm in cell_of if cell_of[nm].startswith(FF)]
    flopset = set(flops)

    memo = {}

    def sources(net, stack=()):
        """Set of 'FF:<inst>' and 'PORT:<name>' that combinationally reach `net`."""
        if net in memo:
            return memo[net]
        if net in stack:
            return set()
        d = driver.get(net)
        if d is None:
            return {f"PORT:{net}"} if net in ports or net in ("I", "clk", "enable", "rst_n") else set()
        if d in flopset:
            return {f"FF:{d}"}
        out = set()
        for pin, n in conns_of[d].items():
            if pin in OUT_PINS or pin in PWR or not n:
                continue
            out |= sources(n, stack + (net,))
        memo[net] = out
        return out

    edges = collections.defaultdict(set)
    for f in flops:
        srcs = set()
        for pin, net in conns_of[f].items():
            if pin in FF_DATA and net:
                srcs |= sources(net)
        edges[f] = srcs

    fanout = collections.defaultdict(set)
    for b, srcs in edges.items():
        for s in srcs:
            if s.startswith("FF:"):
                fanout[s[3:]].add(b)

    nxt = {}
    for b, srcs in edges.items():
        ff_srcs = {s[3:] for s in srcs if s.startswith("FF:")}
        if len(ff_srcs) == 1:
            a = ff_srcs.pop()
            if len(fanout[a]) == 1:
                nxt[a] = b
    heads = [f for f in flops if f in nxt and f not in nxt.values()]
    chains = []
    for h in heads:
        ch, cur = [h], h
        while cur in nxt:
            cur = nxt[cur]
            ch.append(cur)
        if len(ch) > 1:
            chains.append(ch)
    chained = {f for ch in chains for f in ch}

    g = {a: {b for b in fanout[a]} for a in flops}
    index, low, onstk, stk, comps, ctr = {}, {}, set(), [], [], [0]

    def strongconnect(root):
        work = [(root, iter(g[root]))]
        index[root] = low[root] = ctr[0]; ctr[0] += 1
        stk.append(root); onstk.add(root)
        while work:
            v, it = work[-1]
            advanced = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = ctr[0]; ctr[0] += 1
                    stk.append(w); onstk.add(w)
                    work.append((w, iter(g[w])))
                    advanced = True
                    break
                elif w in onstk:
                    low[v] = min(low[v], index[w])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stk.pop(); onstk.discard(w); comp.append(w)
                    if w == v: break
                comps.append(comp)

    for f in flops:
        if f not in index:
            strongconnect(f)
    sccs = sorted([c for c in comps if len(c) > 1], key=len, reverse=True)
    selfloop = [f for f in flops if f in fanout[f] and all(f not in c for c in sccs)]

    succ_src = sources("success")
    o_bits = [n for n in ports if re.match(r"O$", n)]
    o_srcs = {}
    for i in range(8):
        net = f"O[{i}]"
        if net in driver or net in ports:
            o_srcs[net] = sources(net)

    R = []
    def p(*a):
        s = " ".join(str(x) for x in a); print(s); R.append(s)

    p("=" * 72)
    p("REGISTER-LEVEL STRUCTURE")
    p("=" * 72)
    p(f"flip-flops: {len(flops)}   "
      f"({collections.Counter(cell_of[f] for f in flops)})")
    p("")
    p(f"-- shift-register chains found: {len(chains)}")
    for ch in sorted(chains, key=len, reverse=True):
        p(f"   length {len(ch):3d}: {ch[0]} -> ... -> {ch[-1]}")
        srcs = {s for s in edges[ch[0]] if not s.startswith("FF:")}
        p(f"              head D fed by: {sorted(srcs) or 'nothing external'}")
    p("")
    p(f"-- feedback groups (SCCs, i.e. counters/FSMs/accumulators): {len(sccs)}")
    for c in sccs:
        ext = set()
        for f in c:
            ext |= {s for s in edges[f] if s.startswith("PORT:")}
        p(f"   size {len(c):3d}  external inputs: {sorted(ext) or 'none'}")
        p(f"            members: {' '.join(sorted(c)[:12])}"
          + (" ..." if len(c) > 12 else ""))
    if selfloop:
        p(f"-- self-looping flops (hold/toggle): {len(selfloop)}")
    p("")
    p(f"-- unchained, non-SCC flops: "
      f"{len([f for f in flops if f not in chained and all(f not in c for c in sccs)])}")
    p("")
    p("-- `success` combinationally depends on:")
    ff_s = sorted(s[3:] for s in succ_src if s.startswith("FF:"))
    pt_s = sorted(s[5:] for s in succ_src if s.startswith("PORT:"))
    p(f"   {len(ff_s)} flops, ports {pt_s}")
    for ch in sorted(chains, key=len, reverse=True):
        n = len(set(ch) & set(ff_s))
        if n:
            p(f"   ...of which {n}/{len(ch)} are in the {len(ch)}-flop chain "
              f"{ch[0]}..{ch[-1]}")
    for c in sccs:
        n = len(set(c) & set(ff_s))
        if n:
            p(f"   ...of which {n}/{len(c)} are in the size-{len(c)} feedback group")
    p("")
    p("-- output bus O[7:0] depends on:")
    for net, s in sorted(o_srcs.items()):
        ff = sorted(x[3:] for x in s if x.startswith("FF:"))
        p(f"   {net:7s}: {len(ff)} flops, ports "
          f"{sorted(x[5:] for x in s if x.startswith('PORT:'))}")

    json.dump({"chains": chains, "sccs": sccs,
               "success_flops": ff_s, "success_ports": pt_s,
               "edges": {k: sorted(v) for k, v in edges.items()}},
              open(f"{outdir}/structure.json", "w"), indent=1)
    open(f"{outdir}/structure.txt", "w").write("\n".join(R) + "\n")
    p("")
    p(f"wrote {outdir}/structure.json and {outdir}/structure.txt")


if __name__ == "__main__":
    sys.setrecursionlimit(100000)
    main(sys.argv[1], sys.argv[2])
