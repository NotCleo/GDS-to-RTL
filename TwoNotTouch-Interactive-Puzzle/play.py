import tkinter as tk
import math


# ============================================================
# STAR BATTLE PUZZLE
# 11 x 11
# ============================================================

REGIONS = [
    list("AAAAABBCDDE"),
    list("AAF AABCCDDE".replace(" ", "")),
    list("AAFBBBBCCDE"),
    list("AAFBGGGECCE"),
    list("FAFBGEEEEEE"),
    list("FFFBGGGEHHH"),
    list("BBBBBBGEHII"),
    list("BJJJGGGEHII"),
    list("BJJKEEEEHII"),
    list("BBJKKEEEHHH"),
    list("BJJKEEEEEEE"),
]

SIZE = 11

# Visual settings
CELL = 65
GRID_X = 55
GRID_Y = 55

BOARD_W = SIZE * CELL
BOARD_H = SIZE * CELL

BG = "#202020"
GRID = "#666666"
REGION = "#FFFFFF"
TEXT = "#FFFFFF"
STAR = "#FFFFFF"
DOT = "#AAAAAA"


# ============================================================
# MAIN WINDOW
# ============================================================

root = tk.Tk()
root.title("Star Battle: 11×11")
root.resizable(False, False)

canvas_width = GRID_X + BOARD_W + 20
canvas_height = GRID_Y + BOARD_H + 70

canvas = tk.Canvas(
    root,
    width=canvas_width,
    height=canvas_height,
    bg="white",
    highlightthickness=0
)

canvas.pack()


# ============================================================
# BOARD STATE
#
# 0 = empty
# 1 = dot
# 2 = star
# ============================================================

state = [
    [0 for _ in range(SIZE)]
    for _ in range(SIZE)
]


# ============================================================
# DRAW STAR
# ============================================================

def star_points(cx, cy, outer_radius, inner_radius):
    points = []

    for i in range(10):
        angle = -math.pi / 2 + i * math.pi / 5

        if i % 2 == 0:
            radius = outer_radius
        else:
            radius = inner_radius

        x = cx + radius * math.cos(angle)
        y = cy + radius * math.sin(angle)

        points.extend([x, y])

    return points


# ============================================================
# DRAW BOARD
# ============================================================

def draw_board():
    canvas.delete("all")

    # --------------------------------------------------------
    # Background
    # --------------------------------------------------------

    canvas.create_rectangle(
        GRID_X,
        GRID_Y,
        GRID_X + BOARD_W,
        GRID_Y + BOARD_H,
        fill=BG,
        outline=""
    )

    # --------------------------------------------------------
    # Thin cell grid
    # --------------------------------------------------------

    for r in range(SIZE + 1):
        y = GRID_Y + r * CELL

        canvas.create_line(
            GRID_X,
            y,
            GRID_X + BOARD_W,
            y,
            fill=GRID,
            width=1
        )

    for c in range(SIZE + 1):
        x = GRID_X + c * CELL

        canvas.create_line(
            x,
            GRID_Y,
            x,
            GRID_Y + BOARD_H,
            fill=GRID,
            width=1
        )

    # --------------------------------------------------------
    # Region boundaries
    #
    # A thick white line is drawn wherever neighboring cells
    # belong to different regions.
    # --------------------------------------------------------

    wall_width = 6

    for r in range(SIZE):
        for c in range(SIZE):

            # Vertical boundary
            if c < SIZE - 1:

                if REGIONS[r][c] != REGIONS[r][c + 1]:

                    x = GRID_X + (c + 1) * CELL

                    canvas.create_line(
                        x,
                        GRID_Y + r * CELL,
                        x,
                        GRID_Y + (r + 1) * CELL,
                        fill=REGION,
                        width=wall_width
                    )

            # Horizontal boundary
            if r < SIZE - 1:

                if REGIONS[r][c] != REGIONS[r + 1][c]:

                    y = GRID_Y + (r + 1) * CELL

                    canvas.create_line(
                        GRID_X + c * CELL,
                        y,
                        GRID_X + (c + 1) * CELL,
                        y,
                        fill=REGION,
                        width=wall_width
                    )

    # --------------------------------------------------------
    # Outer border
    # --------------------------------------------------------

    canvas.create_rectangle(
        GRID_X,
        GRID_Y,
        GRID_X + BOARD_W,
        GRID_Y + BOARD_H,
        outline=REGION,
        width=7
    )

    # --------------------------------------------------------
    # Coordinates
    # --------------------------------------------------------

    for c in range(SIZE):

        x = GRID_X + c * CELL + CELL / 2

        canvas.create_text(
            x,
            GRID_Y - 25,
            text=str(c + 1),
            fill="black",
            font=("Arial", 18, "bold")
        )

    for r in range(SIZE):

        y = GRID_Y + r * CELL + CELL / 2

        canvas.create_text(
            GRID_X - 25,
            y,
            text=str(r + 1),
            fill="black",
            font=("Arial", 18, "bold")
        )

    # --------------------------------------------------------
    # Draw dots and stars
    # --------------------------------------------------------

    for r in range(SIZE):
        for c in range(SIZE):

            cx = GRID_X + c * CELL + CELL / 2
            cy = GRID_Y + r * CELL + CELL / 2

            if state[r][c] == 1:

                # Dot
                radius = 5

                canvas.create_oval(
                    cx - radius,
                    cy - radius,
                    cx + radius,
                    cy + radius,
                    fill=DOT,
                    outline=""
                )

            elif state[r][c] == 2:

                # Star
                points = star_points(
                    cx,
                    cy,
                    24,
                    10
                )

                canvas.create_polygon(
                    points,
                    fill=STAR,
                    outline=""
                )

    # --------------------------------------------------------
    # Title
    # --------------------------------------------------------

    canvas.create_text(
        GRID_X + BOARD_W / 2,
        GRID_Y + BOARD_H + 32,
        text="Star Battle",
        fill="black",
        font=("Arial", 24, "bold")
    )


# ============================================================
# GET CELL FROM MOUSE POSITION
# ============================================================

def get_cell(event):

    x = event.x - GRID_X
    y = event.y - GRID_Y

    if x < 0 or y < 0:
        return None

    col = x // CELL
    row = y // CELL

    if not (0 <= row < SIZE and 0 <= col < SIZE):
        return None

    return int(row), int(col)


# ============================================================
# SINGLE CLICK
#
# Empty -> Dot
# Dot   -> Empty
# Star  -> Empty
#
# A small delay is used so that a double click can be
# recognized as a star rather than a dot followed by another
# click.
# ============================================================

pending_click = None
pending_after_id = None


def perform_single_click(row, col):

    global pending_click
    global pending_after_id

    pending_click = None
    pending_after_id = None

    # Empty -> dot
    if state[row][col] == 0:
        state[row][col] = 1

    # Dot -> empty
    elif state[row][col] == 1:
        state[row][col] = 0

    # Star -> empty
    elif state[row][col] == 2:
        state[row][col] = 0

    draw_board()

    check_solution()


# ============================================================
# SINGLE CLICK HANDLER
# ============================================================

def single_click(event):

    global pending_click
    global pending_after_id

    cell = get_cell(event)

    if cell is None:
        return

    row, col = cell

    # Cancel any previous pending click
    if pending_after_id is not None:
        root.after_cancel(pending_after_id)

    pending_click = (row, col)

    # Wait briefly to see if this becomes a double click.
    pending_after_id = root.after(
        250,
        lambda: perform_single_click(row, col)
    )


# ============================================================
# DOUBLE CLICK
#
# Any double click makes the cell a STAR.
# ============================================================

def double_click(event):

    global pending_click
    global pending_after_id

    cell = get_cell(event)

    if cell is None:
        return

    row, col = cell

    # Cancel the pending single click.
    if pending_after_id is not None:

        root.after_cancel(
            pending_after_id
        )

        pending_after_id = None

    pending_click = None

    # Double click = star
    state[row][col] = 2

    draw_board()

    check_solution()


# ============================================================
# CHECK ROWS
# ============================================================

def check_rows():

    for r in range(SIZE):

        count = sum(
            state[r][c] == 2
            for c in range(SIZE)
        )

        if count != 2:
            return False

    return True


# ============================================================
# CHECK COLUMNS
# ============================================================

def check_columns():

    for c in range(SIZE):

        count = sum(
            state[r][c] == 2
            for r in range(SIZE)
        )

        if count != 2:
            return False

    return True


# ============================================================
# CHECK REGIONS
# ============================================================

def check_regions():

    region_names = set()

    for row in REGIONS:
        for region in row:
            region_names.add(region)

    for region_name in region_names:

        count = 0

        for r in range(SIZE):
            for c in range(SIZE):

                if REGIONS[r][c] == region_name:

                    if state[r][c] == 2:
                        count += 1

        if count != 2:
            return False

    return True


# ============================================================
# CHECK THAT STARS DON'T TOUCH
#
# Includes:
#   horizontal
#   vertical
#   diagonal
# ============================================================

def check_no_touching_stars():

    for r in range(SIZE):
        for c in range(SIZE):

            if state[r][c] != 2:
                continue

            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):

                    if dr == 0 and dc == 0:
                        continue

                    nr = r + dr
                    nc = c + dc

                    if (
                        0 <= nr < SIZE
                        and 0 <= nc < SIZE
                    ):

                        if state[nr][nc] == 2:
                            return False

    return True


# ============================================================
# FINAL SOLUTION CHECK
# ============================================================

def check_solution():

    if not check_rows():
        return False

    if not check_columns():
        return False

    if not check_regions():
        return False

    if not check_no_touching_stars():
        return False

    # --------------------------------------------------------
    # Puzzle solved!
    # --------------------------------------------------------

    print()
    print("================================")
    print("       PUZZLE SOLVED!")
    print("================================")
    print()

    # Small delay so the final star is visible.
    root.after(
        500,
        root.destroy
    )

    return True


# ============================================================
# MOUSE EVENTS
# ============================================================

canvas.bind(
    "<Button-1>",
    single_click
)

canvas.bind(
    "<Double-Button-1>",
    double_click
)


# ============================================================
# START
# ============================================================

draw_board()

root.mainloop()
