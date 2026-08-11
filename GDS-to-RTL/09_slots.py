#!/usr/bin/env python3
"""
Recover the *meaning* of each 2-flop state pair by finding which counter value
("time slot") gates it.

The design turns out to be built from 2-bit saturating counters, each of the form

    MSB.D = MSB | (LSB & TRIGGER)          <- short expression
    LSB.D = ... TRIGGER ...                <- long expression

where TRIGGER is `I & running & <counter matches some constant>`. This script
pulls the counter-bit literals out of each pair's TRIGGER and prints, per pair,
which counter bits must be 0 and which must be 1 -- i.e. the slot the pair
watches. That is what tells you the pair is "row 3" or "column 7".

Usage: python 09_slots.py <netlist.v> <liberty.lib> <structure.json> <outdir>
"""
import sys, re, json, collections, importlib.util

here = __import__("os").path.dirname(__import__("os").path.abspath(__file__))
spec = importlib.util.spec_from_file_location("dec", f"{here}/08_decompile.py")
dec = importlib.util.module_from_spec(spec); spec.loader.exec_module(dec)


def main(netlist, lib, structjson, outdir):
    insts = dec.parse_netlist(netlist)
    D = dec.Decompiler(insts, dec.liberty_functions(lib))
    st = json.load(open(structjson))
    pairs = [c for c in st["sccs"] if len(c) == 2]

    succ_expr = dec.simplify(D.expr(D.conns_of["u28_dfrtp_2"]["D"]))

    rows = []
    for a, b in pairs:
        ea = dec.simplify(D.expr(D.conns_of[a]["D"]))
        eb = dec.simplify(D.expr(D.conns_of[b]["D"]))
        lsb, msb = (a, b) if len(ea) > len(eb) else (b, a)
        trig = dec.simplify(D.expr(D.conns_of[msb]["D"]))
        lits = {}
        for m in re.finditer(r"(!?)(u\d+_dfrtp_2)\.Q", trig):
            neg, f = m.group(1) == "!", m.group(2)
            if f in (lsb, msb):
                continue
            lits.setdefault(f, set()).add(0 if neg else 1)
        slot = {f: next(iter(v)) for f, v in lits.items() if len(v) == 1}
        rows.append({"lsb": lsb, "msb": msb, "slot": slot, "trigger": trig})

    allbits = collections.Counter()
    for r in rows:
        allbits.update(r["slot"].keys())

    R = []
    def p(*a):
        s = " ".join(str(x) for x in a); print(s); R.append(s)

    p("=" * 78)
    p("2-BIT SATURATING COUNTERS AND THE SLOT EACH ONE WATCHES")
    p("=" * 78)
    p(f"pairs found: {len(rows)}")
    p("")
    p("counter bits referenced by pair triggers (bit -> how many pairs use it):")
    for f, n in allbits.most_common():
        p(f"   {f}: {n}")
    p("")
    bits = [f for f, _ in allbits.most_common()]
    bits.sort()
    p(f"slot decoding, bit order {bits}")
    p("")
    p(f"{'LSB flop':16s} {'MSB flop':16s} {'slot bits':>28s}  required count")
    for r in sorted(rows, key=lambda r: tuple(r["slot"].get(b, -1) for b in bits)):
        pat = "".join(str(r["slot"].get(b, "-")) for b in bits)
        want = "?"
        if re.search(rf"!{r['lsb']}\.Q&{r['msb']}\.Q", succ_expr) or \
           re.search(rf"{r['msb']}\.Q&\(?!{r['lsb']}\.Q", succ_expr):
            want = "2"
        if re.search(rf"{r['lsb']}\.Q&\(?!{r['msb']}\.Q", succ_expr) or \
           re.search(rf"!{r['msb']}\.Q&{r['lsb']}\.Q", succ_expr):
            want = "1"
        if f"{r['lsb']}." not in succ_expr and f"{r['msb']}." not in succ_expr:
            want = "not checked"
        p(f"{r['lsb']:16s} {r['msb']:16s} {pat:>28s}  {want}")

    CAP = 4000
    slim = [{k: (v[:CAP] + " ...[truncated]" if isinstance(v, str) and len(v) > CAP
                 else v) for k, v in r.items()} for r in rows]
    json.dump(slim, open(f"{outdir}/slots.json", "w"), indent=1)
    open(f"{outdir}/slots.txt", "w").write("\n".join(R) + "\n")
    p("")
    p(f"wrote {outdir}/slots.json, {outdir}/slots.txt")


if __name__ == "__main__":
    sys.setrecursionlimit(100000)
    main(*sys.argv[1:5])
