---
name: write-paper
description: Write a workshop-style paper from verified experiment results
---
Write a paper from the verified results in this folder. Put everything in `paper/`.

- `paper/paper.tex` and `paper/refs.bib`: a 4–8 page workshop paper with abstract,
  introduction, related work, method, experiments, results, limitations, conclusion.
- `paper/figures/`: generate every figure with a script (`paper/figures/make_figures.py`)
  that reads `experiments/runs/*/metrics.json`. No hand-drawn numbers.
- Only cite papers listed in `literature.md` or that you look up and confirm exist.
  Every bib entry needs a URL or DOI.
- Report negative or mixed results honestly. The limitations section names what was not
  tested.
- Compile to `paper/paper.pdf` with `tectonic`, `latexmk` or `pdflatex`, whichever is
  installed. If none is installed, leave the .tex and say so in your notes.

If review notes are handed to you, fix each listed problem and do not change unrelated text.
