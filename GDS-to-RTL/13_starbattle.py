#!/usr/bin/env python3
"""
Solve the recovered Star Battle independently of the chip, and check uniqueness.

The point of this script is *corroboration*. The BMC found an input that makes
`success` fire, but that only proves the input is accepted -- it says nothing
about whether the puzzle is well posed. Here we take the constraint set read out
of the silicon (2 stars per row, per column, per region; no two stars touching,
diagonals included), solve it from scratch with z3, and enumerate every
solution. If there is exactly one, and it equals the BMC's answer, the
reverse-engineering is confirmed from two independent directions.

Usage: python 13_starbattle.py <regions.json> [expected_bitstring]
"""
import sys, json, collections
from z3 import Bool, Solver, Sum, If, Not, And, Or, sat

N = 11
STARS = 2


def main():
    regions = json.load(open(sys.argv[1]))["region_of_cell"]
    expected = sys.argv[2] if len(sys.argv) > 2 else None
    reg = {int(k): v for k, v in regions.items()}
    bylabel = collections.defaultdict(list)
    for cell, lab in reg.items():
        bylabel[lab].append(cell)

    g = [[Bool(f"g{r}_{c}") for c in range(N)] for r in range(N)]
    s = Solver()
    for r in range(N):
        s.add(Sum([If(g[r][c], 1, 0) for c in range(N)]) == STARS)
    for c in range(N):
        s.add(Sum([If(g[r][c], 1, 0) for r in range(N)]) == STARS)
    for lab, cells in bylabel.items():
        s.add(Sum([If(g[k // N][k % N], 1, 0) for k in cells]) == STARS)
    for r in range(N):
        for c in range(N):
            for dr, dc in ((0, 1), (1, -1), (1, 0), (1, 1)):
                rr, cc = r + dr, c + dc
                if 0 <= rr < N and 0 <= cc < N:
                    s.add(Not(And(g[r][c], g[rr][cc])))

    print(f"regions: {len(bylabel)}  sizes: "
          f"{ {k: len(v) for k, v in sorted(bylabel.items())} }")
    sols = []
    while s.check() == sat:
        m = s.model()
        grid = [[bool(m.evaluate(g[r][c])) for c in range(N)] for r in range(N)]
        sols.append(grid)
        s.add(Or([g[r][c] != grid[r][c] for r in range(N) for c in range(N)]))
        if len(sols) > 5:
            break

    print(f"\nSOLUTIONS FOUND: {len(sols)}"
          + ("  <-- UNIQUE, the puzzle is well posed" if len(sols) == 1 else ""))
    for i, grid in enumerate(sols):
        bits = "".join("1" if grid[r][c] else "0" for r in range(N) for c in range(N))
        print(f"\nsolution {i}:  bitstream (row-major) = {bits}")
        print("     " + " ".join(f"{c}" for c in range(N)))
        for r in range(N):
            cells = " ".join("*" if grid[r][c] else "." for c in range(N))
            regs = "".join(reg[r * N + c] for c in range(N))
            print(f"  {r:2d} {cells}    {regs}")
        if expected:
            print(f"  matches BMC answer: {bits == expected[:121]}")


if __name__ == "__main__":
    main()
