`timescale 1ns/1ps
module tb_probe;
  reg clk=0, rst_n=0, I=0, enable=0;
  wire success; wire [7:0] O;
  integer k, i;
  puzzle_extracted dut(.clk(clk), .rst_n(rst_n), .I(I), .enable(enable),
             .success(success), .O(O));
  always #5 clk = ~clk;
  initial begin
    for (k=0; k<121; k=k+1) begin
      rst_n=0; enable=0; I=0;
      @(posedge clk); @(posedge clk); @(negedge clk);
      rst_n=1; enable=1;
      for (i=0; i<121; i=i+1) begin
        I = (i==k);
        @(posedge clk); @(negedge clk);
      end
      I=0;
      $display("CELL %0d %b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b%b", k, dut.u178_dfrtp_2.Q, dut.u106_dfrtp_2.Q, dut.u179_dfrtp_2.Q, dut.u107_dfrtp_2.Q, dut.u180_dfrtp_2.Q, dut.u108_dfrtp_2.Q, dut.u189_dfrtp_2.Q, dut.u117_dfrtp_2.Q, dut.u190_dfrtp_2.Q, dut.u118_dfrtp_2.Q, dut.u153_dfrtp_2.Q, dut.u121_dfrtp_2.Q, dut.u141_dfrtp_2.Q, dut.u122_dfrtp_2.Q, dut.u143_dfrtp_2.Q, dut.u123_dfrtp_2.Q, dut.u142_dfrtp_2.Q, dut.u124_dfrtp_2.Q, dut.u188_dfrtp_2.Q, dut.u126_dfrtp_2.Q, dut.u209_dfrtp_2.Q, dut.u194_dfrtp_2.Q, dut.u215_dfrtp_2.Q, dut.u197_dfrtp_2.Q, dut.u226_dfrtp_2.Q, dut.u198_dfrtp_2.Q, dut.u233_dfrtp_2.Q, dut.u231_dfrtp_2.Q, dut.u601_dfrtp_2.Q, dut.u232_dfrtp_2.Q, dut.u661_dfrtp_2.Q, dut.u595_dfrtp_2.Q, dut.u600_dfrtp_2.Q, dut.u622_dfrtp_2.Q, dut.u596_dfrtp_2.Q, dut.u614_dfrtp_2.Q, dut.u597_dfrtp_2.Q, dut.u625_dfrtp_2.Q, dut.u634_dfrtp_2.Q, dut.u603_dfrtp_2.Q, dut.u635_dfrtp_2.Q, dut.u602_dfrtp_2.Q, dut.u647_dfrtp_2.Q, dut.u651_dfrtp_2.Q, dut.u416_dfrtp_2.Q, dut.u420_dfrtp_2.Q);
    end
    $finish;
  end
endmodule
