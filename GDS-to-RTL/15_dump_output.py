#!/usr/bin/env python3
"""
Drive the extracted netlist with a known input sequence and dump the RAW O[7:0]
bus every cycle.

Why not reuse 09's decoder? That one only prints O when it *changes*, which
silently drops repeated characters ("LL" -> "L") and hides the framing. To read
a serial output stream correctly you must first see the raw per-cycle bus and
work out the protocol (how many cycles per character, is there a strobe), then
decode. This script does step one.

Usage:
  python 15_dump_output.py <netlist.v> <models.v> <top> <bitstring> <tail> <outdir>

<bitstring> is the value of I at cycle 1,2,3,...; `enable` is held high for the
whole bitstring and then held high through the tail as well.
"""
import os, sys, subprocess, re

TB = """`timescale 1ns/1ps
module tb_dump;
  reg clk=0, rst_n=0, I=0, enable=0;
  wire success; wire [7:0] O;
  integer i;
  reg [{NM1}:0] seq = {N}'b{BITS};
  {TOP} dut(.clk(clk), .rst_n(rst_n), .I(I), .enable(enable),
             .success(success), .O(O));
  always #5 clk = ~clk;
  initial begin
    $dumpfile("{VCD}"); $dumpvars(0, tb_dump);
    rst_n=0; enable=0; I=0;
    @(posedge clk); @(posedge clk); rst_n=1; @(negedge clk);
    enable=1;
    for (i=0;i<{N};i=i+1) begin
      I = seq[{NM1}-i];
      @(posedge clk);
      $display("CYC %0d I=%b success=%b O=%02h", i+1, I, success, O);
      @(negedge clk);
    end
    I = 0;
    for (i=0;i<{TAIL};i=i+1) begin
      @(posedge clk);
      $display("CYC %0d I=%b success=%b O=%02h", {N}+i+1, I, success, O);
      @(negedge clk);
    end
    $finish;
  end
endmodule
"""


def main():
    netlist, models, top, bits, tail, outdir = sys.argv[1:7]
    n = len(bits)
    vcd = os.path.join(outdir, "dump.vcd")
    tb = os.path.join(outdir, "tb_dump.v")
    open(tb, "w").write(TB.format(N=n, NM1=n - 1, BITS=bits, TOP=top,
                                  TAIL=int(tail), VCD=vcd))
    vvp = os.path.join(outdir, "dump.vvp")
    r = subprocess.run(f"iverilog -g2012 -o {vvp} {models} {netlist} {tb}",
                       shell=True, capture_output=True, text=True)
    if r.returncode:
        print(r.stdout + r.stderr); sys.exit(1)
    r = subprocess.run(f"vvp {vvp}", shell=True, capture_output=True, text=True)
    log = r.stdout
    open(os.path.join(outdir, "dump.log"), "w").write(log)

    rows = []
    for m in re.finditer(r"CYC (\d+) I=(\d) success=(\w) O=([0-9a-fx]+)", log):
        rows.append((int(m.group(1)), m.group(2), m.group(3), m.group(4)))

    first_succ = next((c for c, i, s, o in rows if s == "1"), None)
    print(f"cycles simulated: {len(rows)}   success first high at cycle: {first_succ}")

    stream = [(c, int(o, 16)) for c, i, s, o in rows if o not in ("xx", "XX")]
    print("\nraw O[7:0] per cycle (only cycles where O changes shown, with run length):")
    prev, start = None, None
    runs = []
    for c, v in stream:
        if v != prev:
            if prev is not None:
                runs.append((start, c - 1, prev))
            prev, start = v, c
    if prev is not None:
        runs.append((start, stream[-1][0], prev))
    for a, b, v in runs:
        ch = chr(v) if 32 <= v < 127 else "."
        print(f"   cycles {a:4d}-{b:4d} ({b-a+1:3d}) = 0x{v:02x} '{ch}'")

    msg = "".join(chr(v) if 32 <= v < 127 else "" for a, b, v in runs)
    print(f"\nMESSAGE (one char per run): {msg!r}")
    open(os.path.join(outdir, "message.txt"), "w").write(msg + "\n")
    print(f"wrote {outdir}/dump.log, {outdir}/message.txt, {vcd}")


if __name__ == "__main__":
    main()
