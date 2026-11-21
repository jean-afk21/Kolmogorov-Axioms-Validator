# Kolmogorov Axioms Validator

A small Tkinter app that checks a finite probability assignment against
Kolmogorov's three axioms.

## Run

```powershell
python probabilty_axioms.py
```

Input format:

- Probability assignment: `a:0.2, b:0.3, c:0.5`
- Events: `a ; b` (outcomes separated by commas, events by semicolons)

Press **Validate** or **Ctrl+Enter**. Sessions are saved to `history.json`
next to the script.

## Test

```powershell
python -m unittest -v
```

The tests cover parsing, all three axiom checks, report rendering, history
validation, and atomic history saves. They do not open a window.
