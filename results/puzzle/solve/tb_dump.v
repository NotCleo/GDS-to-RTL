`timescale 1ns/1ps
module tb_dump;
  reg clk=0, rst_n=0, I=0, enable=0;
  wire success; wire [7:0] O;
  integer i;
  reg [122:0] seq = 123'b000000010101000010000000000001010101000000000000101000000100000100000010000010100001000000010000001000001001000101000000000;
  puzzle_extracted dut(.clk(clk), .rst_n(rst_n), .I(I), .enable(enable),
             .success(success), .O(O));
  always #5 clk = ~clk;
  initial begin
    $dumpfile("results/puzzle/solve/dump.vcd"); $dumpvars(0, tb_dump);
    rst_n=0; enable=0; I=0;
    @(posedge clk); @(posedge clk); rst_n=1; @(negedge clk);
    enable=1;
    for (i=0;i<123;i=i+1) begin
      I = seq[122-i];
      @(posedge clk);
      $display("CYC %0d I=%b success=%b O=%02h", i+1, I, success, O);
      @(negedge clk);
    end
    I = 0;
    for (i=0;i<40;i=i+1) begin
      @(posedge clk);
      $display("CYC %0d I=%b success=%b O=%02h", 123+i+1, I, success, O);
      @(negedge clk);
    end
    $finish;
  end
endmodule
