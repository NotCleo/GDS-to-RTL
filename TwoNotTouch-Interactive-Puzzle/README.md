#### Note : 

    1. play.py uses <tkinter> and <math>, both are built-in Python modules, do not need to use pip install to get them.
    2. the puzzle is not timed, it auto closes once the puzzle is solved
    3. no clues provided in the game window
    4. to win, ensure you fill in the non-star elements too (mimicing below solved illustration will not auto-close to indicate puzzle solved)

----

#### Here's how the 11x11 Two-Not-Touch puzzle looks : 

![An unsolved 11x11 Two Not Touch board](../Images/puzzle.png)

----

#### Here's how the solved 11x11 Two-Not-Touch puzzle looks : 

![The same board solved, 22 stars placed](../Images/solved-puzzle.png)

----

#### Instructions to play the puzzle live: 

    git clone https://github.com/NotCleo/GDS-to-RTL.git
    cd GDS-to-RTL/TwoNotTouch-Interactive-Puzzle
    python3 play.py

#### If you want to play without cloning this repo : 

    mkdir puzzle-player
    cd puzzle-player
    <place the play.py file into puzzle-player>
    python3 play.py 
     
#### Once the game window opens : 

    single click : puts a dot / non-star element
    double click : puts a star element
    single click any element to remove it
    
