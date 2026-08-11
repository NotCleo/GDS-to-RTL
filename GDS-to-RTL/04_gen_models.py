#!/usr/bin/env python3
"""
Generate Verilog simulation models for sky130 cells FROM THE LIBERTY FILE.

The Liberty (.lib) file is the "datasheet" of the standard-cell library: for
every cell it lists pins, directions, timing -- and for combinational outputs,
the boolean 'function'. We translate those functions to Verilog assigns.
Sequential cells (Liberty 'ff' groups) get behavioral always-blocks.

This is exactly how you avoid trusting hand-written truth tables: the same
file that told the synthesizer what a cell does now tells our simulator.

Usage: python 04_gen_models.py <liberty> <out.v> [cell_type ...]
       (cell types like sky130_fd_sc_hd__nand2_2; default = a common set)
"""
import sys, re

def cell_blocks(text):
    """Yield (cellname, body) for each cell(...) group, brace-matched."""
    for m in re.finditer(r'cell\s*\(\s*"?([\w\[\]]+)"?\s*\)\s*\{', text):
        depth, i = 1, m.end()
        while depth and i < len(text):
            if text[i] == '{': depth += 1
            elif text[i] == '}': depth -= 1
            i += 1
        yield m.group(1), text[m.end():i - 1]

def pin_info(body):
    pins = []
    for m in re.finditer(r'pin\s*\(\s*"?([\w\[\]]+)"?\s*\)\s*\{', body):
        depth, i = 1, m.end()
        while depth and i < len(body):
            if body[i] == '{': depth += 1
            elif body[i] == '}': depth -= 1
            i += 1
        pb = body[m.end():i - 1]
        d = re.search(r'direction\s*:\s*"?(\w+)"?', pb)
        f = re.search(r'function\s*:\s*"([^"]+)"', pb)
        pins.append((m.group(1), d.group(1) if d else "?", f.group(1) if f else None))
    ff = re.search(r'ff\s*\(\s*"?(\w+)"?\s*,\s*"?(\w+)"?\s*\)\s*\{(.*?)\}', body, re.S)
    return pins, ff

def lib2verilog(expr):
    """Liberty boolean -> Verilog: ' postfix-invert becomes ~( ), ! stays, ^ stays,
    bare juxtaposition (rare) not handled -- sky130 always uses & | explicitly."""
    expr = re.sub(r"(\w+)'", r"~\1", expr)
    expr = re.sub(r"\)'", r")~", expr)
    return expr.replace("!", "~").replace("*", "&").replace("+", "|")

SEQ_TEMPLATES = {
    "dfrtp": """  reg q_int = 1'b0;
  always @(posedge CLK or negedge RESET_B)
    if (!RESET_B) q_int <= 1'b0; else q_int <= D;
  assign Q = q_int;""",
    "dfstp": """  reg q_int = 1'b1;
  always @(posedge CLK or negedge SET_B)
    if (!SET_B) q_int <= 1'b1; else q_int <= D;
  assign Q = q_int;""",
    "dfxtp": """  reg q_int;
  always @(posedge CLK) q_int <= D;
  assign Q = q_int;""",
    "dfxbp": """  reg q_int;
  always @(posedge CLK) q_int <= D;
  assign Q = q_int;  assign Q_N = ~q_int;""",
    "dfrbp": """  reg q_int = 1'b0;
  always @(posedge CLK or negedge RESET_B)
    if (!RESET_B) q_int <= 1'b0; else q_int <= D;
  assign Q = q_int;  assign Q_N = ~q_int;""",
    "dfbbn": """  reg q_int = 1'b0;
  always @(negedge CLK_N or negedge RESET_B or negedge SET_B)
    if (!RESET_B) q_int <= 1'b0;
    else if (!SET_B) q_int <= 1'b1;
    else q_int <= D;
  assign Q = q_int;  assign Q_N = ~q_int;""",
}

def main(lib_path, out_path, wanted):
    text = open(lib_path).read()
    done, out = set(), []
    for cname, body in cell_blocks(text):
        if wanted and cname not in wanted: continue
        if cname in done: continue
        done.add(cname)
        pins, ff = pin_info(body)
        sig = [(n, d, f) for n, d, f in pins if n not in ("VPWR", "VGND", "VPB", "VNB")]
        ports = ", ".join(n for n, d, f in sig)
        lines = [f"module {cname} ({ports});"]
        for n, d, f in sig:
            lines.append(f"  {'input ' if d == 'input' else 'output'} {n};")
        short = cname.split("__")[-1]
        base = re.sub(r"_\d+$", "", short)
        if ff or base in SEQ_TEMPLATES:
            tpl = SEQ_TEMPLATES.get(base)
            if tpl is None:
                print(f"WARNING: sequential cell {cname} has no template -- ADD ONE"); continue
            lines.append(tpl)
        else:
            for n, d, f in sig:
                if d == "output" and f:
                    lines.append(f"  assign {n} = {lib2verilog(f)};")
        lines.append("endmodule\n")
        out.append("\n".join(lines))
    for stub in ("decap_3", "decap_4", "decap_6", "decap_8", "decap_12", "tapvpwrvgnd_1",
                 "fill_1", "fill_2", "fill_4", "fill_8", "diode_2"):
        out.append(f"module sky130_fd_sc_hd__{stub} ();\nendmodule\n")
    with open(out_path, "w") as f:
        f.write(f"// auto-generated from {lib_path.split('/')[-1]} -- do not trust, verify :)\n" + "\n".join(out))
    missing = set(wanted) - done if wanted else set()
    print(f"generated {len(done)} cell models -> {out_path}" + (f"  MISSING: {missing}" if missing else ""))

if __name__ == "__main__":
    wanted = sys.argv[3:]
    if not wanted:
        wanted = ["sky130_fd_sc_hd__" + c for c in
                  "nand2_2 and2_2 and3_2 and4bb_2 or2_2 nor2_2 xor2_2 xnor2_2 a31o_2 a21o_2 a21bo_2 a21boi_2 o21bai_2 mux2_1 clkbuf_16 dfrtp_2".split()]
    main(sys.argv[1], sys.argv[2], wanted)
