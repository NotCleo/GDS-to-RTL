#!/usr/bin/env python3
"""
Produce a "good" VCD -- the one Jane Street didn't give you -- in which the
winning grid is shifted in and `success` actually goes high.

It is deliberately shaped like `example_inputs.vcd` so the two can be opened
side by side in Surfer:
  * same six signals, same names: clk, rst_n, enable, I, O[7:0], success
  * same $timescale 1ps and same 10000 ps clock period
  * same reset/enable choreography: rst_n released at t=30000, enable at
    t=40000, first data cell sampled on the rising edge at t=45000
  * `I` changes on falling edges and is sampled on rising edges, as theirs does

The waveform is produced by simulating the netlist extracted from puzzle.gds,
so O[7:0] and success are whatever the recovered silicon really does -- nothing
here is hand-written into the file.

Usage: python 16_make_vcd.py <netlist.v> <models.v> <top> <bits121> <outfile>
"""
import os, sys, subprocess, re

TB = """`timescale 1ps/1ps
// Top module is named `puzzle` so the VCD scope matches example_inputs.vcd.
module puzzle;
  reg clk = 0, rst_n = 0, enable = 0, I = 0;
  wire [7:0] O;
  wire       success;
  integer k;
  reg [120:0] grid = 121'b{BITS};

  {TOP} dut (.clk(clk), .rst_n(rst_n), .I(I), .enable(enable),
              .success(success), .O(O));

  always #5000 clk = ~clk;          // 10 ns period, rising edges at 5000+n*10000

  initial begin
    $dumpfile("{VCD}");
    // name the six signals explicitly -- $dumpvars(1, puzzle) would also drag
    // in the testbench's loop counter and grid literal
    $dumpvars(0, clk, rst_n, enable, I, O, success);
    #30000 rst_n  = 1;              // release reset on a falling edge
    #10000 enable = 1;              // start the frame
    for (k = 0; k < 121; k = k + 1) begin
      I = grid[120-k];              // row-major: cell 0 first
      #10000;                       // one full clock, sampled at the rising edge
    end
    I = 0;
    #400000;                        // let success latch and the message stream out
    $finish;
  end
endmodule
"""


def main():
    netlist, models, top, bits, outfile = sys.argv[1:6]
    bits = bits[:121]
    assert len(bits) == 121, f"need 121 grid bits, got {len(bits)}"
    outfile = os.path.abspath(outfile)
    tmp = os.path.dirname(outfile) or "."
    tbp = os.path.join(tmp, "tb_makevcd.v")
    open(tbp, "w").write(TB.format(BITS=bits, TOP=top, VCD=outfile))

    vvp = os.path.join(tmp, "makevcd.vvp")
    r = subprocess.run(f"iverilog -g2012 -o {vvp} {models} {netlist} {tbp}",
                       shell=True, capture_output=True, text=True)
    if r.returncode:
        print(r.stdout + r.stderr); sys.exit(1)
    subprocess.run(f"vvp {vvp}", shell=True, capture_output=True, text=True)
    os.remove(vvp); os.remove(tbp)

    txt = open(outfile).read()
    ids = dict(re.findall(r"\$var \w+ \d+ (\S+) (\w+)", txt))
    id_success = next(k for k, v in ids.items() if v == "success")
    id_o       = next(k for k, v in ids.items() if v == "O")
    t, succ_t, chars, seen = 0, None, [], None
    for line in txt.splitlines():
        line = line.strip()
        if line.startswith("#"):
            t = int(line[1:])
        elif line[:1] in "01" and line[1:] == id_success:
            if line[0] == "1" and succ_t is None:
                succ_t = t
        elif line.startswith("b") and line.endswith(" " + id_o):
            v = int(line[1:-len(id_o) - 1].strip() or "0", 2)
            if v and v != seen:
                chars.append(chr(v))
            seen = v
    print(f"wrote {outfile}  ({os.path.getsize(outfile)} bytes)")
    print(f"  signals   : {sorted(ids.values())}")
    print(f"  success   : first high at t={succ_t} ps"
          f"  (rising edge {(succ_t - 5000)//10000 + 1})")
    print(f"  O[7:0]    : {''.join(chars)!r}")
    if succ_t is None:
        print("  !! success never went high -- do not ship this file"); sys.exit(1)


if __name__ == "__main__":
    main()
