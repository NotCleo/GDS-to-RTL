#!/usr/bin/env python3
"""
Decompile a flat gate netlist back into readable boolean equations.

For any net, walk backwards through combinational cells and print the logic as
an expression, stopping at flip-flop Q outputs and primary inputs. This turns
"o21a_2 whose A1 comes from a nand2_2 whose..." into `(a | b) & c`, which is
what you actually need to understand the design.

Cell functions come from the Liberty file, so this is exact -- no hand-written
truth-table table to get wrong.

Usage:
  python 08_decompile.py <netlist.v> <liberty.lib> <net> [<net> ...]
  python 08_decompile.py <netlist.v> <liberty.lib> --flop <instname>
  python 08_decompile.py <netlist.v> <liberty.lib> --all-flops
"""
import sys, re, collections

OUT_PINS = {"X", "Y", "Q", "Q_N", "HI", "LO"}
PWR = {"VPWR", "VGND", "VPB", "VNB"}
FF = ("dfrtp", "dfstp", "dfxtp", "dfbbn", "dfrbp", "dfxbp")


def liberty_functions(path):
    """{cellname: {outpin: function_string}} from a Liberty .lib."""
    txt = open(path).read()
    out = {}
    for cm in re.finditer(r"\n\s*cell\s*\(\s*\"?([\w$]+)\"?\s*\)\s*\{", txt):
        name = cm.group(1)
        i, depth = cm.end() - 1, 0
        while i < len(txt):
            if txt[i] == "{": depth += 1
            elif txt[i] == "}":
                depth -= 1
                if depth == 0: break
            i += 1
        body = txt[cm.end():i]
        pins = {}
        for pm in re.finditer(r"\n\s*pin\s*\(\s*\"?(\w+)\"?\s*\)\s*\{", body):
            j, d = pm.end() - 1, 0
            while j < len(body):
                if body[j] == "{": d += 1
                elif body[j] == "}":
                    d -= 1
                    if d == 0: break
                j += 1
            pb = body[pm.end():j]
            fn = re.search(r'\n\s*function\s*:\s*"([^"]*)"', pb)
            if fn and re.search(r'\n\s*direction\s*:\s*"?output', pb):
                pins[pm.group(1)] = fn.group(1)
        if pins:
            out[name] = pins
    return out


def parse_netlist(path):
    txt = open(path).read()
    insts = []
    for m in re.finditer(r"(sky130_fd_sc_hd__\w+)\s+(\w+)\s*\(([^;]*)\);", txt, re.S):
        cell, name, body = m.groups()
        conns = {k: v.strip() for k, v in re.findall(r"\.(\w+)\(([^)]*)\)", body)}
        insts.append((cell, name, conns))
    return insts


def fn_to_py(fn, conns):
    """Translate a Liberty function string into a python-ish infix expression,
    substituting each pin name with a placeholder that we later expand."""
    fn = fn.replace("*", "&").replace("+", "|")
    prev = None
    while prev != fn:
        prev = fn
        fn = re.sub(r"(\w+)\s*'", r"!\1", fn)
        fn = re.sub(r"\)\s*'", r")'CLOSENOT'", fn)
    fn = re.sub(r"([\w\)])\s+(?=[\w\(!])", r"\1 & ", fn)
    return fn


class Decompiler:
    def __init__(self, insts, libfns):
        self.conns_of = {nm: c for _, nm, c in insts}
        self.cell_of = {nm: c for c, nm, _ in insts}
        self.driver = {}
        for cell, nm, conns in insts:
            for pin, net in conns.items():
                if pin in OUT_PINS and net:
                    self.driver[net] = (nm, pin)
        self.libfns = libfns
        self.flops = {nm for nm in self.cell_of
                      if self.cell_of[nm].split("__")[-1].startswith(FF)}
        self.count = collections.Counter()

    def expr(self, net, depth=0, maxdepth=40, seen=()):
        if net in ("1'b0", "1'b1"): return net
        d = self.driver.get(net)
        if d is None:
            return net
        inst, pin = d
        if inst in self.flops:
            self.count[inst] += 1
            return f"{inst}.{pin}"
        if depth >= maxdepth or net in seen:
            return net
        cell = self.cell_of[inst]
        short = cell.split("__")[-1]
        if short.startswith("conb"):
            return "1'b1" if pin == "HI" else "1'b0"
        if short.startswith(("buf", "clkbuf")):
            return self.expr(self.conns_of[inst]["A"], depth, maxdepth, seen + (net,))
        fn = self.libfns.get(cell, {}).get(pin)
        if fn is None:
            return f"<{cell}.{pin}>"
        body = fn_to_py(fn, self.conns_of[inst])
        def sub(m):
            p = m.group(0)
            if p not in self.conns_of[inst]:
                return p
            return "(" + self.expr(self.conns_of[inst][p], depth + 1,
                                   maxdepth, seen + (net,)) + ")"
        body = re.sub(r"\b[A-Z][A-Z0-9_]*\b", sub, body)
        return body.replace("'CLOSENOT'", "")


def simplify(s):
    """cosmetic: collapse ((x)) and !(!(x))"""
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"\(\s*\(([^()]*)\)\s*\)", r"(\1)", s)
        s = re.sub(r"!\(!\(([^()]*)\)\)", r"(\1)", s)
        s = re.sub(r"\(([\w\.\[\]]+)\)", r"\1", s)
    return s


def main():
    netlist, lib = sys.argv[1], sys.argv[2]
    args = sys.argv[3:]
    D = Decompiler(parse_netlist(netlist), liberty_functions(lib))

    if args and args[0] == "--all-flops":
        targets = [("flop", f) for f in sorted(D.flops)]
    elif args and args[0] == "--flop":
        targets = [("flop", a) for a in args[1:]]
    else:
        targets = [("net", a) for a in args]

    for kind, t in targets:
        if kind == "flop":
            c = D.conns_of[t]
            print(f"\n### {t}  ({D.cell_of[t].split('__')[-1]})")
            for pin in ("D", "SET_B", "RESET_B", "SCD", "SCE"):
                if pin in c:
                    D.count.clear()
                    e = simplify(D.expr(c[pin]))
                    print(f"  {pin} = {e}")
        else:
            D.count.clear()
            print(f"\n### net {t}")
            print(f"  = {simplify(D.expr(t))}")


if __name__ == "__main__":
    sys.setrecursionlimit(100000)
    main()
