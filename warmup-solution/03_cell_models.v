// sky130 cell models generated from sky130_fd_sc_hd__tt_025C_1v80.lib
// 18 cells. Source of truth is the Liberty 'function' / 'ff' data, not hand-written tables.

module sky130_fd_sc_hd__a21bo_2 (A1, A2, B1_N, X);
  input  A1;
  input  A2;
  input  B1_N;
  output X;
  assign X = (A1&A2) | (~B1_N);
endmodule

module sky130_fd_sc_hd__a21boi_2 (A1, A2, B1_N, Y);
  input  A1;
  input  A2;
  input  B1_N;
  output Y;
  assign Y = (~A1&B1_N) | (~A2&B1_N);
endmodule

module sky130_fd_sc_hd__a21o_2 (A1, A2, B1, X);
  input  A1;
  input  A2;
  input  B1;
  output X;
  assign X = (A1&A2) | (B1);
endmodule

module sky130_fd_sc_hd__a31o_2 (A1, A2, A3, B1, X);
  input  A1;
  input  A2;
  input  A3;
  input  B1;
  output X;
  assign X = (A1&A2&A3) | (B1);
endmodule

module sky130_fd_sc_hd__and2_2 (A, B, X);
  input  A;
  input  B;
  output X;
  assign X = (A&B);
endmodule

module sky130_fd_sc_hd__and3_2 (A, B, C, X);
  input  A;
  input  B;
  input  C;
  output X;
  assign X = (A&B&C);
endmodule

module sky130_fd_sc_hd__and4bb_2 (A_N, B_N, C, D, X);
  input  A_N;
  input  B_N;
  input  C;
  input  D;
  output X;
  assign X = (~A_N&~B_N&C&D);
endmodule

module sky130_fd_sc_hd__clkbuf_16 (A, X);
  input  A;
  output X;
  assign X = (A);
endmodule

module sky130_fd_sc_hd__decap_3 ();
endmodule

module sky130_fd_sc_hd__dfrtp_2 (CLK, D, Q, RESET_B);
  input  CLK;
  input  D;
  output Q;
  input  RESET_B;
  reg q = 1'b0;
  always @(posedge CLK or negedge RESET_B)
    if (!RESET_B) q <= 1'b0;
    else q <= D;
  assign Q = q;
endmodule

module sky130_fd_sc_hd__mux2_1 (A0, A1, S, X);
  input  A0;
  input  A1;
  input  S;
  output X;
  assign X = (A0&~S) | (A1&S);
endmodule

module sky130_fd_sc_hd__nand2_2 (A, B, Y);
  input  A;
  input  B;
  output Y;
  assign Y = (~A) | (~B);
endmodule

module sky130_fd_sc_hd__nor2_2 (A, B, Y);
  input  A;
  input  B;
  output Y;
  assign Y = (~A&~B);
endmodule

module sky130_fd_sc_hd__o21bai_2 (A1, A2, B1_N, Y);
  input  A1;
  input  A2;
  input  B1_N;
  output Y;
  assign Y = (~A1&~A2) | (B1_N);
endmodule

module sky130_fd_sc_hd__or2_2 (A, B, X);
  input  A;
  input  B;
  output X;
  assign X = (A) | (B);
endmodule

module sky130_fd_sc_hd__tapvpwrvgnd_1 ();
endmodule

module sky130_fd_sc_hd__xnor2_2 (A, B, Y);
  input  A;
  input  B;
  output Y;
  assign Y = (~A&~B) | (A&B);
endmodule

module sky130_fd_sc_hd__xor2_2 (A, B, X);
  input  A;
  input  B;
  output X;
  assign X = (A&~B) | (~A&B);
endmodule
