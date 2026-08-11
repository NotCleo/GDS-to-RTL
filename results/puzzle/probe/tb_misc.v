`timescale 1ns/1ps
module tb_misc;
  reg clk=0, rst_n=0, I=0, enable=0;
  wire success; wire [7:0] O;
  integer k, i, ns, m;
  reg [121-1:0] sol = 121'b0000000101010000100000000000010101010000000000001010000001000001000000100000101000010000000100000010000010010001010000000;
  puzzle_extracted dut(.clk(clk), .rst_n(rst_n), .I(I), .enable(enable),
             .success(success), .O(O));
  always #5 clk = ~clk;
  initial begin
    // ---- part 1: star-count sweep. k stars dropped on cells 0,4,8,... ----
    for (k=0; k<=24; k=k+1) begin
      rst_n=0; enable=0; I=0;
      @(posedge clk); @(posedge clk); @(negedge clk);
      rst_n=1; enable=1;
      for (i=0; i<121; i=i+1) begin
        I = (i % 4 == 0) && ((i/4) < k);
        @(posedge clk); @(negedge clk);
      end
      I=0;
      $display("NSTARS %0d REG %b%b%b%b%b%b%b%b", k, dut.u447_dfrtp_2.Q, dut.u449_dfrtp_2.Q, dut.u451_dfrtp_2.Q, dut.u453_dfrtp_2.Q, dut.u454_dfrtp_2.Q, dut.u459_dfrtp_2.Q, dut.u460_dfrtp_2.Q, dut.u461_dfrtp_2.Q);
    end
    // ---- part 2: the message catalogue. Drive four classes of grid and read
    // O[7:0] back. The wrong ones are dead code no correct solve ever reaches,
    // so the only way to see them is to deliberately fail. ----
    for (m=0; m<4; m=m+1) begin
      rst_n=0; enable=0; I=0;
      @(posedge clk); @(posedge clk); @(negedge clk);
      rst_n=1; enable=1;
      for (i=0; i<121; i=i+1) begin
        case (m)
          0: I = 1'b0;                  // no stars at all
          1: I = 1'b1;                  // every cell a star
          2: I = (i % 4 == 0);          // 31 stars, structurally wrong
          3: I = sol[121-1-i];      // the real answer
        endcase
        @(posedge clk); @(negedge clk);
      end
      I=0;
      for (i=0; i<40; i=i+1) begin
        $display("MSGOUT %0d %0d %0h success=%b", m, i, O, success);
        @(posedge clk); @(negedge clk);
      end
    end
    $finish;
  end
endmodule
