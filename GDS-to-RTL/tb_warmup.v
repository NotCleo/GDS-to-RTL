// Testbench: drive the GOLDEN netlist (01_netlist.v, module adder_demo) and
// our EXTRACTED netlist (from 04_final.gds, module adder_demo_extracted) with
// the same stimulus and require their outputs to be identical, cycle by cycle.
// Then load specific A/B bytes serially and check S == (A+B == 496).
`timescale 1ns/1ps
module tb_warmup;
  reg clk = 0, rst_n = 0, en = 0, A = 0, B = 0;
  wire S_gold, S_extr;
  integer errors = 0;

  adder_demo           dut_gold (.clk(clk), .rst_n(rst_n), .A(A), .B(B), .S(S_gold), .en(en));
  adder_demo_extracted dut_extr (.clk(clk), .rst_n(rst_n), .A(A), .B(B), .S(S_extr), .en(en));

  always #5 clk = ~clk;

  always @(negedge clk)
    if (rst_n && S_gold !== S_extr) begin
      errors = errors + 1;
      $display("MISMATCH at %0t: golden S=%b extracted S=%b", $time, S_gold, S_extr);
    end

  // shift one byte into both shift registers, MSB first
  // (parallel_out <= {parallel_out[6:0], serial_in} means the first bit
  //  shifted in ends up in bit 7 after eight shifts)
  task load_bytes(input [7:0] va, input [7:0] vb);
    integer i;
    begin
      rst_n = 0; en = 0; @(negedge clk); rst_n = 1; @(negedge clk);
      en = 1;
      for (i = 7; i >= 0; i = i - 1) begin
        A = va[i]; B = vb[i]; @(negedge clk);
      end
      en = 0; A = 0; B = 0; @(negedge clk);
    end
  endtask

  task check(input [7:0] va, input [7:0] vb);
    begin
      load_bytes(va, vb);
      $display("A=%0d B=%0d  sum=%0d  ->  S=%b (expected %b)  %s",
               va, vb, va + vb, S_gold, (va + vb == 496),
               (S_gold === (va + vb == 496)) ? "OK" : "WRONG");
      if (S_gold !== (va + vb == 496)) errors = errors + 1;
    end
  endtask

  integer n;
  reg [7:0] ra, rb;
  initial begin
    $dumpfile("results/warmup/warmup.vcd");
    $dumpvars(0, tb_warmup);

    // ---- phase 1: random equivalence torture ----
    rst_n = 0; repeat (2) @(negedge clk); rst_n = 1;
    for (n = 0; n < 3000; n = n + 1) begin
      en = $random; A = $random; B = $random;
      if (n % 500 == 499) begin rst_n = 0; @(negedge clk); rst_n = 1; end
      @(negedge clk);
    end
    $display("phase 1 (random equivalence, 3000 cycles): %0d mismatches", errors);

    // ---- phase 2: random functional check vs A+B==496 ----
    for (n = 0; n < 200; n = n + 1) begin
      ra = $random; rb = $random;
      load_bytes(ra, rb);
      if (S_gold !== (ra + rb == 496)) begin
        errors = errors + 1;
        $display("FUNC WRONG: A=%0d B=%0d S=%b", ra, rb, S_gold);
      end
    end
    $display("phase 2 (200 random byte pairs): done");

    // ---- phase 3: directed ----
    check(8'd255, 8'd241);   // 496 -> S=1
    check(8'd248, 8'd248);   // 496 -> S=1
    check(8'd255, 8'd240);   // 495 -> S=0
    check(8'd100, 8'd100);   // 200 -> S=0

    if (errors == 0) $display("ALL CHECKS PASSED: extracted netlist == golden netlist, and S <=> (A+B==496)");
    else             $display("FAILED with %0d errors", errors);
    $finish;
  end
endmodule
