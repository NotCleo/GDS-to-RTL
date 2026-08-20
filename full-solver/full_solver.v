// ===========================================================================
// full_solver.v -- solver in front of validator, wired as in proposed-module.png
//
// THE HANDOVER
//
// The validator has no idea any of this is happening. It is the chip as it came
// off the die, and the only way to talk to it is the protocol it already has:
// hold rst_n low until you mean it, raise enable, then present one grid cell per
// rising edge for 121 edges and read success on the 122nd.
//
// So the sequencer here holds the validator in reset for the whole time the
// solver is working, and then does exactly what the drawing says.
//
//   edge 1 .. 121            the region map streams into the solver
//   edge 122                 one clock to set the search up
//   edge 123 .. 121+x        the search runs, x clocks in total including 122
//   edge 121+x+1             the handover. rst_n is released and enable is
//                            raised. The validator does not move on this edge:
//                            it still sees the old reset, which is the point of
//                            spending a clock on it
//   edge 121+x+2 .. 121+x+122
//                            121 edges of the solved frame, most significant
//                            bit first, which is row 0 column 0 first
//   edge 244+x               the 122nd enabled edge. success rises and latches,
//                            and O[7:0] begins the verdict
//
// x is whatever the search costs. For the region map on the die it is 10126
// clocks, so success arrives on edge 10370.
// ===========================================================================
module full_solver #(parameter N = 11) (
  input  wire       clk,
  input  wire       rst_n,
  input  wire       enable,
  input  wire [3:0] region_in,
  output wire       success,
  output wire [7:0] O,
  output wire       solved,
  output wire       unsat,
  output wire [31:0] steps
);
  wire [120:0] solution;

  solver #(N) U_SOLVER (
    .clk(clk), .rst_n(rst_n), .enable(enable), .region_in(region_in),
    .solved(solved), .unsat(unsat), .solution(solution), .steps(steps));

  reg       val_rst_n, val_en, feeding, armed;
  reg [6:0] feed;

  wire I = feeding ? solution[120 - feed] : 1'b0;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      val_rst_n <= 1'b0; val_en <= 1'b0;
      feeding   <= 1'b0; armed  <= 1'b0; feed <= 7'd0;
    end else if (solved && !armed) begin
      armed     <= 1'b1;
      val_rst_n <= 1'b1;
      val_en    <= 1'b1;
      feeding   <= 1'b1;
      feed      <= 7'd0;
    end else if (feeding) begin
      if (feed == 7'd120) feeding <= 1'b0;
      else                feed    <= feed + 1'b1;
    end
  end

  validator #(N) U_VALIDATOR (
    .clk(clk), .rst_n(val_rst_n), .I(I), .enable(val_en),
    .success(success), .O(O));
endmodule
