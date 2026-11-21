"""Kolmogorov axioms validator.

A small Tkinter application that checks whether a finite probability
assignment satisfies Kolmogorov's three axioms.

The validation and history code is deliberately independent of Tkinter so
it can be tested without opening a window.
"""

from __future__ import annotations

import json
import math
import os
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from tkinter import messagebox, simpledialog, ttk
from tkinter import font as tkfont
from typing import Callable, Sequence
from uuid import uuid4

from gavel_animation import GavelAnimation

TOL = 1e-9
NEGATIVE_TOL = 1e-12
MAX_HISTORY = 200
SIDEBAR_WIDTH = 270
LEFT_MIN_WIDTH = 680
DATE_FORMAT = "%b {day}, %Y · {hour}:{minute} %p"
AXIOM_DELAY_MS = 600
DOTS_MS = 1000
SPINNER_MS = 100
VERDICT_VALID = "valid"
VERDICT_INVALID = "invalid"


# ---------------------------------------------------------------
# BLOCK 1: Parsing helpers (turn the user's text into Python data)
# ---------------------------------------------------------------
def parse_pmf(text: str) -> dict[str, float]:
    """Convert ``'a:0.2, b:0.3, c:0.5'`` into a probability dict.

    Raises ``ValueError`` with a user-facing message for malformed input.
    """
    pmf: dict[str, float] = {}
    for raw_part in text.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if ":" not in part:
            raise ValueError(f"'{part}' must look like outcome:probability")

        name, value = part.split(":", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            raise ValueError("An outcome name is empty.")
        if name in pmf:
            raise ValueError(f"Outcome '{name}' is listed twice.")

        try:
            probability = float(value)
        except ValueError:
            raise ValueError(f"'{value}' is not a number.") from None
        if not math.isfinite(probability):
            raise ValueError(f"P({name}) must be a finite number, not {value!r}.")

        pmf[name] = probability

    if not pmf:
        raise ValueError("Please enter at least one outcome.")
    return pmf


def parse_events(text: str, pmf: dict[str, float]) -> list[set[str]]:
    """Convert ``'a,b ; c'`` into ``[{'a', 'b'}, {'c'}]``."""
    events: list[set[str]] = []
    outcomes = set(pmf)
    for chunk in text.split(";"):
        names = {name.strip() for name in chunk.split(",") if name.strip()}
        if not names:
            continue
        unknown = names - outcomes
        if unknown:
            raise ValueError(
                f"Not in the sample space: {', '.join(sorted(unknown))}"
            )
        events.append(names)
    return events


# ---------------------------------------------------------------
# BLOCK 2: The axiom checks (the "brain" of the program)
# ---------------------------------------------------------------
def prob(pmf: dict[str, float], event: set[str]) -> float:
    """P(event) = sum of the probabilities of the outcomes in it."""
    return math.fsum(pmf[outcome] for outcome in event)


def check_axiom1(pmf: dict[str, float]) -> tuple[bool, dict[str, float]]:
    """Axiom 1: every probability must be >= 0."""
    negatives = {
        outcome: value
        for outcome, value in pmf.items()
        if value < -NEGATIVE_TOL
    }
    return not negatives, negatives


def check_axiom2(pmf: dict[str, float]) -> tuple[bool, float]:
    """Axiom 2: P(S) = 1, so all probabilities must add up to 1."""
    total = math.fsum(pmf.values())
    return math.isclose(total, 1.0, abs_tol=TOL), total


def are_disjoint(events: Sequence[set[str]]) -> bool:
    """True if no two events share an outcome.

    This is O(total number of outcomes) instead of comparing every pair of
    events, which matters when the user supplies many events.
    """
    seen: set[str] = set()
    for event in events:
        if not seen.isdisjoint(event):
            return False
        seen.update(event)
    return True


def check_axiom3(
    pmf: dict[str, float], events: Sequence[set[str]]
) -> tuple[bool, float, float]:
    """Axiom 3: for disjoint events, P(union) = sum of P(each)."""
    union: set[str] = set()
    for event in events:
        union.update(event)

    p_union = prob(pmf, union)
    p_sum = math.fsum(prob(pmf, event) for event in events)
    return math.isclose(p_union, p_sum, abs_tol=TOL), p_union, p_sum


# ---------------------------------------------------------------
# BLOCK 3: Structured validation results
# ---------------------------------------------------------------
@dataclass(frozen=True)
class CheckResult:
    """One axiom check. ``ok`` is ``None`` when the check was skipped."""

    title: str
    ok: bool | None
    detail: str = ""


@dataclass(frozen=True)
class ValidationReport:
    checks: tuple[CheckResult, ...]
    valid: bool


def validate_assignment(
    pmf: dict[str, float], events: Sequence[set[str]]
) -> ValidationReport:
    """Run all three axioms and return a structured report."""
    checks: list[CheckResult] = []

    ok1, negatives = check_axiom1(pmf)
    if ok1:
        checks.append(
            CheckResult("Axiom 1 (P(A) >= 0)", True, "all probabilities are non-negative")
        )
    else:
        detail = ", ".join(
            f"P({outcome}) = {value:g}" for outcome, value in negatives.items()
        )
        checks.append(CheckResult("Axiom 1 (P(A) >= 0)", False, detail))

    ok2, total = check_axiom2(pmf)
    checks.append(
        CheckResult("Axiom 2 (P(S) = 1)", ok2, f"sum = {total:.6g}")
    )

    if len(events) < 2:
        checks.append(
            CheckResult(
                "Axiom 3 (additivity)",
                None,
                "enter at least 2 events",
            )
        )
    elif not are_disjoint(events):
        checks.append(
            CheckResult(
                "Axiom 3 (additivity)",
                False,
                "the events are not disjoint (they share an outcome)",
            )
        )
    else:
        ok3, p_union, p_sum = check_axiom3(pmf, events)
        detail = (
            f"P(union) = {p_union:.6g},  "
            f"sum of P(each) = {p_sum:.6g}"
        )
        checks.append(CheckResult("Axiom 3 (additivity)", ok3, detail))

    valid = all(check.ok is not False for check in checks)
    return ValidationReport(tuple(checks), valid)


def render_report(report: ValidationReport) -> list[tuple[str, str]]:
    """Turn a report into ``(text, tag)`` lines for the results pane."""
    lines: list[tuple[str, str]] = [("RESULTS", "head"), ("", "")]
    for check in report.checks:
        suffix = f"  ({check.detail})" if check.detail else ""
        if check.ok is None:
            lines.append((f"{check.title}: SKIPPED{suffix}", "head"))
        elif check.ok:
            lines.append((f"{check.title}: PASS{suffix}", "pass"))
        else:
            lines.append((f"{check.title}: FAIL  ->  {check.detail}", "fail"))

    lines.append(("", ""))
    if report.valid:
        lines.append(("VERDICT: VALID probability assignment", "pass"))
    else:
        lines.append(("VERDICT: INVALID probability assignment", "fail"))
    return lines


def input_error_lines(message: str) -> list[tuple[str, str]]:
    """Result lines for malformed input."""
    return [
        (f"Input error: {message}", "fail"),
        ("VERDICT: INVALID probability assignment", "fail"),
    ]


# ---------------------------------------------------------------
# BLOCK 4: History model and atomic persistence
# ---------------------------------------------------------------
@dataclass
class HistoryEntry:
    id: str
    session_number: int
    title: str
    created_at: str
    pmf: str
    events: str
    lines: list[tuple[str, str]]
    verdict: str
    pinned: bool = False
    created: str | None = None
    modified: str | None = None

    @classmethod
    def from_dict(cls, data: object) -> "HistoryEntry":
        """Validate and convert one decoded JSON object."""
        if not isinstance(data, dict):
            raise ValueError("session must be a JSON object")

        def text(key: str) -> str:
            value = data.get(key)
            if not isinstance(value, str):
                raise ValueError(f"'{key}' must be a string")
            return value

        session_id = text("id")
        if not session_id:
            raise ValueError("'id' must not be empty")

        session_number = data.get("session_number")
        if (
            not isinstance(session_number, int)
            or isinstance(session_number, bool)
            or session_number < 1
        ):
            raise ValueError("'session_number' must be a positive integer")

        verdict = text("verdict")
        if verdict not in (VERDICT_VALID, VERDICT_INVALID):
            raise ValueError("'verdict' must be 'valid' or 'invalid'")

        pinned = data.get("pinned")
        if not isinstance(pinned, bool):
            raise ValueError("'pinned' must be true or false")

        raw_lines = data.get("lines")
        if not isinstance(raw_lines, list):
            raise ValueError("'lines' must be a list")
        lines: list[tuple[str, str]] = []
        for line in raw_lines:
            if (
                not isinstance(line, list)
                or len(line) != 2
                or not all(isinstance(part, str) for part in line)
            ):
                raise ValueError("each line must be a [text, tag] pair of strings")
            lines.append((line[0], line[1]))

        created_at = text("created_at")
        try:
            datetime.fromisoformat(created_at)
        except ValueError:
            raise ValueError("'created_at' must be an ISO-8601 timestamp") from None

        created = data.get("created", None)
        modified = data.get("modified", None)
        return cls(
            id=session_id,
            session_number=session_number,
            title=text("title"),
            created_at=created_at,
            pmf=text("pmf"),
            events=text("events"),
            lines=lines,
            verdict=verdict,
            pinned=pinned,
            created=created if isinstance(created, str) else None,
            modified=modified if isinstance(modified, str) else None,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "session_number": self.session_number,
            "title": self.title,
            "created_at": self.created_at,
            "created": self.created,
            "modified": self.modified,
            "pmf": self.pmf,
            "events": self.events,
            "lines": [[text, tag] for text, tag in self.lines],
            "verdict": self.verdict,
            "pinned": self.pinned,
        }


class HistoryStore:
    """Load and save the history file atomically."""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> list[HistoryEntry]:
        try:
            with self.path.open("r", encoding="utf-8") as history_file:
                raw = json.load(history_file)
        except FileNotFoundError:
            return []
        except json.JSONDecodeError as err:
            raise ValueError(f"history file is not valid JSON: {err}") from err

        if not isinstance(raw, list):
            raise ValueError("the history file must contain a list of sessions")

        entries: list[HistoryEntry] = []
        seen_ids: set[str] = set()
        for index, item in enumerate(raw, start=1):
            try:
                entry = HistoryEntry.from_dict(item)
            except ValueError as err:
                raise ValueError(f"session #{index}: {err}") from err
            if entry.id in seen_ids:
                raise ValueError(f"session #{index}: duplicate session id")
            seen_ids.add(entry.id)
            entries.append(entry)
        return entries

    def save(self, entries: Sequence[HistoryEntry]) -> None:
        """Write to a temporary file, then replace the real one.

        A crash mid-write can no longer truncate the user's history.
        """
        data = [entry.to_dict() for entry in entries]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as history_file:
                json.dump(data, history_file, ensure_ascii=False, indent=2)
                history_file.flush()
                os.fsync(history_file.fileno())
                temp_path = Path(history_file.name)
            os.replace(temp_path, self.path)
        finally:
            if temp_path is not None and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass


# ---------------------------------------------------------------
# BLOCK 5: The GUI class
# ---------------------------------------------------------------
class AxiomsApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.store = HistoryStore(Path(__file__).with_name("history.json"))
        self.history: list[HistoryEntry] = []
        self.sidebar_visible = True
        self._active_session_id: str | None = None
        self.animation_running = False
        self._animation_after_ids: list[str] = []
        self._animation_lines: list[tuple[str, str]] = []
        self._animation_checks: list[CheckResult] = []
        self._animation_valid = False
        self._closing = False

        root.title("Kolmogorov Axioms Validator")
        root.geometry("960x600")
        root.minsize(LEFT_MIN_WIDTH + SIDEBAR_WIDTH, 480)

        self._build_ui()
        self._load_history()
        self.load_valid()
        self._refresh_history_list()

    # -----------------------------------------------------------
    # BLOCK 6: Building the interface
    # -----------------------------------------------------------
    def _build_ui(self) -> None:
        # The main column expands; the history column stays fixed-width.
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        main = ttk.Frame(self.root, padding=12)
        main.grid(row=0, column=0, sticky="nsew")
        self.sidebar = ttk.Frame(self.root, width=SIDEBAR_WIDTH)
        self.sidebar.grid(row=0, column=1, sticky="ns")
        self.sidebar.grid_propagate(False)
        ttk.Separator(self.sidebar, orient="vertical").grid(
            row=0, column=0, sticky="ns"
        )
        sidebar_content = ttk.Frame(self.sidebar, padding=(8, 12, 12, 12))
        sidebar_content.grid(row=0, column=1, sticky="nsew")
        self.sidebar.grid_columnconfigure(1, weight=1)
        self.sidebar.grid_rowconfigure(0, weight=1)

        # --- Optional session title ---
        main_header = ttk.Frame(main)
        main_header.pack(fill="x", pady=(0, 8))
        self.sidebar_toggle_button = ttk.Button(
            main_header, text="Hide history", command=self._toggle_sidebar
        )
        self.sidebar_toggle_button.pack(side="right")

        ttk.Label(
            main,
            text="Session title (optional)",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")
        self.title_entry = ttk.Entry(main, font=("Segoe UI", 10))
        self.title_entry.pack(fill="x", pady=(2, 10))

        # --- Input area ---
        ttk.Label(
            main,
            text="Probability assignment (outcome:probability, separated by commas)",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")
        self.pmf_entry = ttk.Entry(main, font=("Consolas", 11))
        self.pmf_entry.pack(fill="x", pady=(2, 10))

        ttk.Label(
            main,
            text="Disjoint events to test additivity (outcomes by commas, events by semicolons)",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")
        self.events_entry = ttk.Entry(main, font=("Consolas", 11))
        self.events_entry.pack(fill="x", pady=(2, 4))
        ttk.Label(
            main,
            text="Example:  a ; b   means events {a} and {b}",
            foreground="gray",
        ).pack(anchor="w", pady=(0, 10))

        # --- Buttons ---
        buttons = ttk.Frame(main)
        buttons.pack(fill="x", pady=(0, 10))
        self.validate_button = ttk.Button(
            buttons, text="Validate", command=self.validate
        )
        self.validate_button.pack(side="left")
        self.valid_example_button = ttk.Button(
            buttons, text="Valid example", command=self.load_valid
        )
        self.valid_example_button.pack(side="left", padx=6)
        self.invalid_example_button = ttk.Button(
            buttons, text="Invalid example", command=self.load_invalid
        )
        self.invalid_example_button.pack(side="left")
        self.skip_animation_var = tk.BooleanVar(master=self.root, value=False)
        ttk.Checkbutton(
            buttons,
            text="Skip animation",
            variable=self.skip_animation_var,
        ).pack(side="left", padx=(10, 0))
        self.clear_button = ttk.Button(
            buttons, text="Clear", command=self.clear
        )
        self.clear_button.pack(side="right")
        ttk.Button(
            buttons, text="Copy results", command=self.copy_results
        ).pack(side="right", padx=(0, 6))

        # --- Results area ---
        self.output = tk.Text(
            main,
            height=14,
            font=("Consolas", 11),
            state="disabled",
            wrap="word",
        )
        self.output.pack(fill="both", expand=True)
        self.output.tag_config("pass", foreground="#1a7f37")
        self.output.tag_config("fail", foreground="#cf222e")
        self.output.tag_config("head", font=("Consolas", 11, "bold"))
        self.gavel = GavelAnimation(self.output)

        self.status_label = ttk.Label(main, text="", foreground="gray")
        self.status_label.pack(fill="x", pady=(6, 0))

        # --- Scrollable history sidebar ---
        self.history_title_font = tkfont.Font(
            root=self.root, font=("Segoe UI", 9)
        )
        ttk.Label(
            sidebar_content,
            text="History",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", pady=(0, 8))
        history_list_frame = ttk.Frame(sidebar_content)
        history_list_frame.pack(fill="both", expand=True)
        self.history_canvas = tk.Canvas(
            history_list_frame, highlightthickness=0, borderwidth=0
        )
        history_scrollbar = ttk.Scrollbar(
            history_list_frame,
            orient="vertical",
            command=self.history_canvas.yview,
        )
        self.history_canvas.configure(yscrollcommand=history_scrollbar.set)
        self.history_canvas.pack(side="left", fill="both", expand=True)
        history_scrollbar.pack(side="right", fill="y")
        self.history_inner = ttk.Frame(self.history_canvas)
        self.history_window = self.history_canvas.create_window(
            (0, 0), window=self.history_inner, anchor="nw"
        )
        self.history_inner.bind("<Configure>", self._update_history_scrollregion)
        self.history_canvas.bind("<Configure>", self._resize_history_content)

        # Keyboard shortcuts: Ctrl+Enter validates.
        self.root.bind("<Control-Return>", self._validate_shortcut)
        self.root.bind("<Control-KP_Enter>", self._validate_shortcut)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # -----------------------------------------------------------
    # BLOCK 7: Existing button and output helpers
    # -----------------------------------------------------------
    def load_valid(self) -> None:
        self._fill("a:0.2, b:0.3, c:0.5", "a ; b")

    def load_invalid(self) -> None:
        self._fill("a:0.5, b:-0.1, c:0.6", "a ; b")

    def _fill(self, pmf_text: str, events_text: str) -> None:
        self._active_session_id = None
        self.pmf_entry.delete(0, tk.END)
        self.pmf_entry.insert(0, pmf_text)
        self.events_entry.delete(0, tk.END)
        self.events_entry.insert(0, events_text)
        self._write([])
        self.pmf_entry.focus_set()

    def clear(self) -> None:
        self.cancel_animation()
        self._fill("", "")
        self.title_entry.delete(0, tk.END)

    def copy_results(self) -> None:
        text = self.output.get("1.0", "end-1c")
        if not text.strip():
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status_label.configure(text="Results copied to clipboard")

    def _write(self, lines: Sequence[tuple[str, str]]) -> None:
        """Replace the results pane with ``(text, tag)`` lines."""
        self.output.config(state="normal")
        self.output.delete("1.0", tk.END)
        for text, tag in lines:
            self.output.insert(tk.END, text + "\n", tag)
        self.output.config(state="disabled")

    # --- Cancellable validation presentation and one-shot gavel ---
    def _set_validation_controls_enabled(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        for button in (
            self.validate_button,
            self.valid_example_button,
            self.invalid_example_button,
            self.clear_button,
        ):
            button.configure(state=state)

    def _schedule_animation(
        self, delay_ms: int, callback: Callable[..., None], *args: object
    ) -> None:
        if self._closing:
            return

        after_id: str | None = None

        def run_callback() -> None:
            if after_id in self._animation_after_ids:
                self._animation_after_ids.remove(after_id)
            if not self._closing:
                callback(*args)

        after_id = self.root.after(delay_ms, run_callback)
        self._animation_after_ids.append(after_id)

    def cancel_animation(self) -> None:
        """Cancel pending animation steps and restore the normal UI state."""
        for after_id in self._animation_after_ids:
            self.root.after_cancel(after_id)
        self._animation_after_ids.clear()
        self.animation_running = False
        self._animation_lines.clear()
        self._animation_checks.clear()
        self.gavel.cancel()
        self._set_validation_controls_enabled(True)

    def _render_animation_lines(self) -> None:
        self._write(self._animation_lines)
        self.output.see(tk.END)

    @staticmethod
    def _animated_check_line(check: CheckResult) -> tuple[str, str]:
        if check.ok is None:
            suffix = f" ({check.detail})" if check.detail else ""
            return f"{check.title}: SKIPPED{suffix}", "head"
        if check.ok:
            suffix = f"  ({check.detail})" if check.detail else ""
            return f"{check.title}: ✓ PASS{suffix}", "pass"
        return f"{check.title}: ✗ FAIL  ->  {check.detail}", "fail"

    def _begin_validation_animation(self, report: ValidationReport) -> None:
        self.animation_running = True
        self._animation_checks = list(report.checks)
        self._animation_valid = report.valid
        self._animation_lines = [("RESULTS", "head"), ("", "")]
        self._set_validation_controls_enabled(False)
        self._show_axiom_step(0)

    def _show_axiom_step(self, check_index: int) -> None:
        if not self.animation_running:
            return
        if check_index >= len(self._animation_checks):
            self._start_dots_animation()
            return

        check = self._animation_checks[check_index]
        if check.ok is None:
            self._animation_lines.append(self._animated_check_line(check))
            self._render_animation_lines()
            self._schedule_animation(0, self._show_axiom_step, check_index + 1)
            return

        axiom_name = " ".join(check.title.split()[:2])
        self._animation_lines.append((f"Checking {axiom_name}... |", "head"))
        self._active_animation_line_index = len(self._animation_lines) - 1
        self._render_animation_lines()
        self._schedule_animation(SPINNER_MS, self._spin_axiom, check_index, 1)

    def _spin_axiom(self, check_index: int, tick: int) -> None:
        if not self.animation_running:
            return

        total_ticks = max(
            1, (AXIOM_DELAY_MS + SPINNER_MS - 1) // SPINNER_MS
        )
        check = self._animation_checks[check_index]
        line_index = self._active_animation_line_index
        if tick >= total_ticks:
            self._animation_lines[line_index] = self._animated_check_line(check)
            self._render_animation_lines()
            self._schedule_animation(0, self._show_axiom_step, check_index + 1)
            return

        frames = "|/-\\"
        axiom_name = " ".join(check.title.split()[:2])
        self._animation_lines[line_index] = (
            f"Checking {axiom_name}... {frames[tick % len(frames)]}",
            "head",
        )
        self._render_animation_lines()
        self._schedule_animation(SPINNER_MS, self._spin_axiom, check_index, tick + 1)

    def _start_dots_animation(self) -> None:
        self._dots_frames = ("● ○ ○", "● ● ○", "● ● ●")
        self._dots_interval_ms = max(1, DOTS_MS // 6)
        self._dots_elapsed_ms = 0
        self._animation_lines.append((self._dots_frames[0], "head"))
        self._render_animation_lines()
        self._schedule_animation(
            min(self._dots_interval_ms, DOTS_MS),
            self._advance_dots_animation,
            1,
        )

    def _advance_dots_animation(self, frame_index: int) -> None:
        if not self.animation_running:
            return
        self._dots_elapsed_ms = min(
            DOTS_MS, self._dots_elapsed_ms + self._dots_interval_ms
        )
        if self._dots_elapsed_ms >= DOTS_MS:
            self.gavel.play(
                valid=self._animation_valid,
                on_done=self._finish_validation_animation,
            )
            return

        self._animation_lines[-1] = (
            self._dots_frames[frame_index % len(self._dots_frames)],
            "head",
        )
        self._render_animation_lines()
        self._schedule_animation(
            min(self._dots_interval_ms, DOTS_MS - self._dots_elapsed_ms),
            self._advance_dots_animation,
            frame_index + 1,
        )

    def _finish_validation_animation(self) -> None:
        verdict = "VALID" if self._animation_valid else "INVALID"
        tag = "pass" if self._animation_valid else "fail"
        self._animation_lines[-1] = ("", "")
        self._animation_lines.append((f"VERDICT: {verdict}", tag))
        self._render_animation_lines()
        self.animation_running = False
        self._set_validation_controls_enabled(True)

    def _on_close(self) -> None:
        self._closing = True
        self.cancel_animation()
        self.root.destroy()

    def _validate_shortcut(self, _event: object = None) -> str:
        self.validate()
        return "break"

    # -----------------------------------------------------------
    # BLOCK 8: Loading and saving session history
    # -----------------------------------------------------------
    def _load_history(self) -> None:
        try:
            self.history = self.store.load()
        except (OSError, ValueError) as err:
            self.history = []
            messagebox.showerror(
                "History error",
                f"Could not load session history from:\n{self.store.path}\n\n"
                f"The history will start empty. Details: {err}",
            )

    def _save_history(self) -> None:
        try:
            self.store.save(self.history)
        except OSError as err:
            messagebox.showerror(
                "History error",
                f"Could not save session history to:\n{self.store.path}\n\n{err}",
            )

    # -----------------------------------------------------------
    # BLOCK 9: Drawing and collapsing the history sidebar
    # -----------------------------------------------------------
    def _toggle_sidebar(self) -> None:
        self.root.update_idletasks()
        current_width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = self.root.winfo_x()
        y = self.root.winfo_y()

        showing = not self.sidebar_visible
        if showing:
            self.sidebar.grid()
            button_text = "Hide history"
            min_width = LEFT_MIN_WIDTH + SIDEBAR_WIDTH
            new_width = current_width + SIDEBAR_WIDTH
            x = min(x, self.root.winfo_screenwidth() - new_width)
        else:
            self.sidebar.grid_remove()
            button_text = "Show history"
            min_width = LEFT_MIN_WIDTH
            new_width = current_width - SIDEBAR_WIDTH

        self.sidebar_visible = showing
        self.sidebar_toggle_button.configure(text=button_text)
        self.root.minsize(min_width, 480)
        self.root.geometry(f"{new_width}x{height}{x:+d}{y:+d}")
        self.root.update_idletasks()

    def _update_history_scrollregion(self, _event: object = None) -> None:
        bbox = self.history_canvas.bbox("all")
        if bbox is not None:
            self.history_canvas.configure(scrollregion=bbox)

    def _resize_history_content(self, event: tk.Event) -> None:
        self.history_canvas.itemconfigure(self.history_window, width=event.width)

    def _refresh_history_list(self) -> None:
        for child in self.history_inner.winfo_children():
            child.destroy()

        pinned = [entry for entry in self.history if entry.pinned]
        recent = [entry for entry in self.history if not entry.pinned]

        ttk.Label(
            self.history_inner, text="Pinned", font=("Segoe UI", 9, "bold")
        ).pack(anchor="w", fill="x", pady=(2, 4))
        if pinned:
            for entry in pinned:
                self._create_history_row(entry)
        else:
            ttk.Label(
                self.history_inner,
                text="No pinned sessions",
                foreground="gray",
            ).pack(anchor="w", padx=6, pady=(0, 8))

        ttk.Label(
            self.history_inner, text="Recent", font=("Segoe UI", 9, "bold")
        ).pack(anchor="w", fill="x", pady=(8, 4))
        if recent:
            for entry in recent:
                self._create_history_row(entry)
        elif not pinned:
            ttk.Label(
                self.history_inner,
                text="No sessions yet",
                foreground="gray",
            ).pack(anchor="w", padx=6, pady=(0, 8))

        total = len(self.history)
        self.status_label.configure(
            text=f"{total} session{'s' if total != 1 else ''} saved"
        )

    def _create_history_row(self, entry: HistoryEntry) -> None:
        row = ttk.Frame(self.history_inner, padding=(4, 5))
        row.pack(fill="x", pady=1)
        row.grid_columnconfigure(1, weight=1)

        dot_color = "#1a7f37" if entry.verdict == VERDICT_VALID else "#cf222e"
        dot = ttk.Label(
            row, text="●", foreground=dot_color, font=("Segoe UI", 9)
        )
        dot.grid(row=0, column=0, sticky="w", padx=(0, 5))

        title = ttk.Label(
            row,
            text=entry.title,
            anchor="w",
            justify="left",
            font=self.history_title_font,
        )
        title.grid(row=0, column=1, sticky="ew")
        title.bind(
            "<Configure>",
            lambda event, label=title, full_title=entry.title: (
                self._fit_history_title(label, full_title, event.width)
            ),
        )

        if entry.pinned:
            pin = ttk.Label(row, text="📌", font=("Segoe UI", 9))
            pin.grid(row=0, column=2, padx=3)

        time_label = ttk.Label(
            row,
            text=self._format_time(entry.created_at),
            foreground="gray",
            font=("Segoe UI", 8),
        )
        time_label.grid(row=0, column=3, padx=(4, 2))

        menu_button = ttk.Button(
            row,
            text="⋯",
            width=3,
            command=lambda session_id=entry.id: self._show_history_menu(
                session_id, menu_button
            ),
        )
        menu_button.grid(row=0, column=4, sticky="e")

        clickable = [row, dot, title, time_label]
        if entry.pinned:
            clickable.append(pin)
        for widget in clickable:
            widget.configure(cursor="hand2")
            widget.bind(
                "<Button-1>",
                lambda _event, session_id=entry.id: self._restore_history(
                    session_id
                ),
            )

    def _fit_history_title(
        self, title_label: ttk.Label, full_title: str, available_width: int
    ) -> None:
        """Truncate titles to their allocated width without squeezing row controls."""
        ellipsis = "..."
        if self.history_title_font.measure(full_title) <= available_width:
            display_title = full_title
        else:
            low, high = 0, len(full_title)
            while low < high:
                middle = (low + high + 1) // 2
                if (
                    self.history_title_font.measure(full_title[:middle] + ellipsis)
                    <= available_width
                ):
                    low = middle
                else:
                    high = middle - 1
            display_title = (
                full_title[:low] + ellipsis
                if self.history_title_font.measure(ellipsis) <= available_width
                else ""
            )

        if title_label.cget("text") != display_title:
            title_label.configure(text=display_title)

    # -----------------------------------------------------------
    # BLOCK 10: Restoring and managing individual sessions
    # -----------------------------------------------------------
    @staticmethod
    def _format_time(timestamp: str) -> str:
        moment = datetime.fromisoformat(timestamp)
        now = datetime.now(moment.tzinfo) if moment.tzinfo else datetime.now()
        if moment.date() == now.date():
            return moment.strftime("%I:%M %p").lstrip("0")
        return moment.strftime("%b %d, %H:%M")

    @staticmethod
    def _format_session_date(timestamp: str | None) -> str:
        if not timestamp:
            return "Unknown"
        try:
            moment = datetime.fromisoformat(timestamp)
        except ValueError:
            return "Unknown"
        return moment.strftime(DATE_FORMAT).format(
            day=moment.day,
            hour=moment.strftime("%I").lstrip("0") or "0",
            minute=moment.strftime("%M"),
        )

    def _find_history_entry(self, session_id: str) -> HistoryEntry | None:
        return next(
            (entry for entry in self.history if entry.id == session_id),
            None,
        )

    def _restore_history(self, session_id: str) -> None:
        self.cancel_animation()
        entry = self._find_history_entry(session_id)
        if entry is None:
            return
        self._active_session_id = session_id
        self.title_entry.delete(0, tk.END)
        self.title_entry.insert(0, entry.title)
        self.pmf_entry.delete(0, tk.END)
        self.pmf_entry.insert(0, entry.pmf)
        self.events_entry.delete(0, tk.END)
        self.events_entry.insert(0, entry.events)
        self._write(entry.lines)
        self.status_label.configure(text=f"Restored '{entry.title}'")

    def _show_history_menu(self, session_id: str, button: ttk.Button) -> None:
        entry = self._find_history_entry(session_id)
        if entry is None:
            return

        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(
            label="Info",
            command=lambda: self._show_session_info(session_id),
        )
        menu.add_command(
            label="Rename",
            command=lambda: self._rename_history_entry(session_id),
        )
        menu.add_command(
            label="Delete",
            command=lambda: self._delete_history_entry(session_id),
        )
        menu.add_command(
            label="Unpin" if entry.pinned else "Pin",
            command=lambda: self._toggle_pin(session_id),
        )
        try:
            menu.tk_popup(
                button.winfo_rootx(),
                button.winfo_rooty() + button.winfo_height(),
            )
        finally:
            menu.grab_release()

    def _show_session_info(self, session_id: str) -> None:
        entry = self._find_history_entry(session_id)
        if entry is None:
            return

        popup = tk.Toplevel(self.root)
        popup.title("Session Info")
        popup.transient(self.root)
        popup.resizable(False, False)

        content = ttk.Frame(popup, padding=12)
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(1, weight=1)
        labels = ("Title:", "Created:", "Last modified:", "Verdict:")
        values = (
            entry.title,
            self._format_session_date(entry.created),
            self._format_session_date(entry.modified),
            "Valid" if entry.verdict == VERDICT_VALID else "Invalid",
        )
        for row, (label_text, value_text) in enumerate(zip(labels, values)):
            ttk.Label(
                content, text=label_text, font=("Segoe UI", 9, "bold")
            ).grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=3)
            value_label = ttk.Label(
                content,
                text=value_text,
                wraplength=360,
                justify="left",
            )
            if label_text == "Verdict:":
                value_label.configure(
                    foreground="#1a7f37"
                    if entry.verdict == VERDICT_VALID
                    else "#cf222e"
                )
            value_label.grid(row=row, column=1, sticky="w", pady=3)

        def close_popup() -> None:
            popup.grab_release()
            popup.destroy()

        ttk.Button(content, text="Close", command=close_popup).grid(
            row=len(labels), column=0, columnspan=2, sticky="e", pady=(10, 0)
        )
        popup.protocol("WM_DELETE_WINDOW", close_popup)
        popup.bind("<Escape>", lambda _event: close_popup())

        self.root.update_idletasks()
        popup.update_idletasks()
        x = self.root.winfo_rootx() + (
            self.root.winfo_width() - popup.winfo_reqwidth()
        ) // 2
        y = self.root.winfo_rooty() + (
            self.root.winfo_height() - popup.winfo_reqheight()
        ) // 2
        x = max(0, min(x, self.root.winfo_screenwidth() - popup.winfo_reqwidth()))
        y = max(
            0, min(y, self.root.winfo_screenheight() - popup.winfo_reqheight())
        )
        popup.geometry(f"+{x}+{y}")
        popup.grab_set()
        popup.focus_set()

    def _rename_history_entry(self, session_id: str) -> None:
        entry = self._find_history_entry(session_id)
        if entry is None:
            return

        new_title = simpledialog.askstring(
            "Rename session",
            "Enter a title for this session:",
            initialvalue=entry.title,
            parent=self.root,
        )
        if new_title is None:
            return

        new_title = new_title.strip()
        if not new_title:
            new_title = (
                f"Session {entry.session_number} · "
                f"{self._format_time(entry.created_at)}"
            )
        entry.title = new_title
        entry.modified = datetime.now().astimezone().isoformat(timespec="seconds")
        self._save_history()
        self._refresh_history_list()

    def _delete_history_entry(self, session_id: str) -> None:
        entry = self._find_history_entry(session_id)
        if entry is None:
            return
        if not messagebox.askyesno(
            "Delete session",
            f"Delete '{entry.title}' from history?",
            parent=self.root,
        ):
            return

        self.history = [
            item for item in self.history if item.id != session_id
        ]
        self._save_history()
        self._refresh_history_list()

    def _toggle_pin(self, session_id: str) -> None:
        entry = self._find_history_entry(session_id)
        if entry is None:
            return
        entry.pinned = not entry.pinned
        entry.modified = datetime.now().astimezone().isoformat(timespec="seconds")
        self._save_history()
        self._refresh_history_list()

    def _prune_history(self) -> None:
        """Keep all pinned sessions and the newest ``MAX_HISTORY`` others."""
        if len(self.history) <= MAX_HISTORY:
            return

        unpinned_seen = 0
        kept: list[HistoryEntry] = []
        for entry in self.history:  # newest first
            if entry.pinned:
                kept.append(entry)
            elif unpinned_seen < MAX_HISTORY:
                kept.append(entry)
                unpinned_seen += 1
        self.history = kept

    def _record_session(
        self, lines: Sequence[tuple[str, str]], verdict: str
    ) -> None:
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        if self._active_session_id is not None:
            active_entry = self._find_history_entry(self._active_session_id)
            if active_entry is not None:
                title = self.title_entry.get().strip()
                if title:
                    active_entry.title = title
                active_entry.pmf = self.pmf_entry.get()
                active_entry.events = self.events_entry.get()
                active_entry.lines = [(text, tag) for text, tag in lines]
                active_entry.verdict = verdict
                active_entry.modified = timestamp
                self._save_history()
                self._refresh_history_list()
                return

        session_number = max(
            (entry.session_number for entry in self.history),
            default=0,
        ) + 1
        title = self.title_entry.get().strip()
        if not title:
            title = (
                f"Session {session_number} · "
                f"{self._format_time(timestamp)}"
            )

        self.history.insert(
            0,
            HistoryEntry(
                id=uuid4().hex,
                session_number=session_number,
                title=title,
                created_at=timestamp,
                pmf=self.pmf_entry.get(),
                events=self.events_entry.get(),
                lines=[(text, tag) for text, tag in lines],
                verdict=verdict,
                pinned=False,
                created=timestamp,
                modified=timestamp,
            ),
        )
        self._prune_history()
        self._save_history()
        self._refresh_history_list()

    # -----------------------------------------------------------
    # BLOCK 11: The main Validate action
    # -----------------------------------------------------------
    def validate(self) -> None:
        if self.animation_running or self._closing:
            return

        # Step 1: read and parse the input
        try:
            pmf = parse_pmf(self.pmf_entry.get())
            events = parse_events(self.events_entry.get(), pmf)
        except ValueError as err:
            messagebox.showerror("Input error", str(err))
            lines = input_error_lines(str(err))
            self._write(lines)
            self._record_session(lines, VERDICT_INVALID)
            return

        # Step 2: run the axiom checks
        report = validate_assignment(pmf, events)
        lines = render_report(report)

        # Save immediately; animation only reveals this already-computed report.
        self._record_session(
            lines, VERDICT_VALID if report.valid else VERDICT_INVALID
        )
        if self.skip_animation_var.get():
            self._write(lines)
            return

        self._begin_validation_animation(report)


# ---------------------------------------------------------------
# BLOCK 12: Program entry point
# ---------------------------------------------------------------
def _enable_windows_dpi_awareness() -> None:
    """Keep text crisp on high-DPI Windows displays."""
    if os.name != "nt":
        return
    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        # DPI awareness is a nice-to-have; never block startup.
        pass


if __name__ == "__main__":
    _enable_windows_dpi_awareness()
    root = tk.Tk()
    app = AxiomsApp(root)
    root.mainloop()
