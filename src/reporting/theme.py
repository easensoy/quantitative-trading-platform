"""Visual identity shared by every report figure: palettes, typography, layout, export.

Figures are 9.2 inches wide (about GitHub's README column at 100 dpi) and exported at
200 dpi, so they stay sharp on high-density screens without shrinking the text.
Positive and negative values use a blue/orange pair, which stays distinguishable with
the common forms of color-vision deficiency, and every signed number also carries an
explicit sign.
"""
from __future__ import annotations

import io
import textwrap
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")  # headless rendering

import matplotlib.pyplot as plt  # noqa: E402
from PIL import Image  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, to_rgb  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

FIGURE_WIDTH = 9.2
EXPORT_DPI = 200
MINUS = "−"


@dataclass(frozen=True)
class Theme:
    name: str
    background: str
    panel: str
    text: str
    muted: str
    faint: str
    grid: str
    spine: str
    cyan: str
    blue: str
    amber: str
    violet: str
    positive: str
    negative: str
    neutral: str
    benchmark: str

    def diverging(self) -> LinearSegmentedColormap:
        return LinearSegmentedColormap.from_list(
            f"{self.name}_diverging", [self.negative, self.panel, self.positive])

    def readable_on(self, color) -> str:
        r, g, b = to_rgb(color)
        luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
        return "#0B1120" if luminance > 0.55 else "#F1F5F9"


DARK = Theme(
    name="dark", background="#0B1120", panel="#0F172A", text="#E2E8F0", muted="#94A3B8",
    faint="#64748B", grid="#1E293B", spine="#334155", cyan="#22D3EE", blue="#60A5FA",
    amber="#FBBF24", violet="#A78BFA", positive="#38BDF8", negative="#F59E0B",
    neutral="#475569", benchmark="#94A3B8",
)
LIGHT = Theme(
    name="light", background="#FFFFFF", panel="#F8FAFC", text="#0F172A", muted="#475569",
    faint="#94A3B8", grid="#E2E8F0", spine="#CBD5E1", cyan="#0891B2", blue="#2563EB",
    amber="#B45309", violet="#7C3AED", positive="#0369A1", negative="#C2410C",
    neutral="#CBD5E1", benchmark="#64748B",
)
THEMES = {"dark": DARK, "light": LIGHT}


def rc_params(theme: Theme) -> dict:
    return {
        "figure.facecolor": theme.background,
        "savefig.facecolor": theme.background,
        "axes.facecolor": theme.panel,
        "axes.edgecolor": theme.spine,
        "axes.labelcolor": theme.muted,
        "axes.titlecolor": theme.text,
        "axes.titlesize": 9.5,
        "axes.titleweight": "semibold",
        "axes.titlelocation": "left",
        "axes.titlepad": 7,
        "axes.labelsize": 8.3,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.axisbelow": True,
        "axes.unicode_minus": True,
        "axes.linewidth": 0.8,
        "text.color": theme.text,
        "font.family": "DejaVu Sans",
        "font.size": 8.3,
        "xtick.color": theme.spine,
        "ytick.color": theme.spine,
        "xtick.labelcolor": theme.muted,
        "ytick.labelcolor": theme.muted,
        "xtick.labelsize": 7.8,
        "ytick.labelsize": 7.8,
        "xtick.major.size": 3,
        "ytick.major.size": 0,
        "grid.color": theme.grid,
        "grid.linewidth": 0.7,
        "legend.frameon": False,
        "legend.fontsize": 7.8,
        "legend.labelcolor": theme.muted,
        "lines.linewidth": 1.35,
        "hatch.color": theme.faint,
        "hatch.linewidth": 0.6,
        "figure.dpi": 100,
        "savefig.dpi": EXPORT_DPI,
    }


@contextmanager
def themed(theme: Theme):
    with plt.rc_context(rc_params(theme)):
        yield


# ---------------------------------------------------------------- formatting

def signed(text_number: str, value: float) -> str:
    return ("+" if value > 0 else "") + text_number.replace("-", MINUS)


def pct(value: float, digits: int = 1, sign: bool = False) -> str:
    text = f"{value * 100:.{digits}f}%"
    return signed(text, value) if sign else text.replace("-", MINUS)


def money(value: float, currency: str = "USD", digits: int = 0, sign: bool = False, compact: bool = False) -> str:
    """Currency text. compact: thousands with no decimals (USD 189k), millions with two
    (USD 1.19M) and billions with one (USD 1.0B), unless digits asks for more."""
    magnitude = abs(value)
    if compact and magnitude >= 1e9:
        body = f"{magnitude / 1e9:.{max(digits, 1)}f}B"
    elif compact and magnitude >= 1e6:
        body = f"{magnitude / 1e6:.{max(digits, 2)}f}M"
    elif compact and magnitude >= 1e3:
        body = f"{magnitude / 1e3:.{digits}f}k"
    else:
        body = f"{magnitude:,.{digits}f}"
    prefix = (MINUS if value < 0 else ("+" if sign and value > 0 else ""))
    return prefix + " ".join(part for part in (currency, body) if part)


def short_money(value: float) -> str:
    """Axis tick text without currency or trailing zeros: 1M, 10M, 1.5B, 900k."""
    magnitude = abs(value)
    for size, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if magnitude >= size:
            text = f"{magnitude / size:.2f}".rstrip("0").rstrip(".") + suffix
            break
    else:
        text = f"{magnitude:.0f}"
    return (MINUS if value < 0 else "") + text


def number(value: float, digits: int = 2, sign: bool = False) -> str:
    text = f"{value:,.{digits}f}"
    return signed(text, value) if sign else text.replace("-", MINUS)


def percent_axis(ax, axis: str = "y", digits: int = 0):
    formatter = FuncFormatter(lambda v, _: pct(v, digits))
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(formatter)


def money_axis(ax, currency: str = "USD", axis: str = "y"):
    formatter = FuncFormatter(lambda v, _: f"{currency} {short_money(v)}".strip())
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(formatter)


# ---------------------------------------------------------------- layout

@dataclass
class Frame:
    fig: plt.Figure
    top: float  # figure fraction where content may start
    bottom: float  # figure fraction where content (including axis labels) must end
    left: float = 0.085
    right: float = 0.975


SUBTITLE_WIDTH = 132  # characters per subtitle line at 8.6 pt across the figure
FOOTER_WIDTH = 178  # characters per footer line at 6.6 pt


def new_frame(theme: Theme, height: float, title: str, subtitle: str, footer: Iterable[str],
              tag: str = "SYNTHETIC DATA · SIMULATED EXECUTION", axis_space: float = 0.42) -> Frame:
    """Figure with a title block, a wrapped subtitle and a provenance footer.

    axis_space (inches) is kept free above the footer for tick and axis labels of the
    lowest panels; Frame.top and Frame.bottom bound the area for the axes themselves.
    """
    fig = plt.figure(figsize=(FIGURE_WIDTH, height))
    edge = 0.30 / FIGURE_WIDTH
    fig.text(edge, 1 - 0.24 / height, title, ha="left", va="top", fontsize=13.5, fontweight="bold",
             color=theme.text)
    sub_lines = textwrap.wrap(subtitle, SUBTITLE_WIDTH)[:2]
    for i, line in enumerate(sub_lines):
        fig.text(edge, 1 - (0.56 + 0.17 * i) / height, line, ha="left", va="top", fontsize=8.6, color=theme.muted)
    if tag:
        fig.text(1 - edge, 1 - 0.26 / height, tag, ha="right", va="top", fontsize=6.9, fontweight="bold",
                 color=theme.amber,
                 bbox=dict(boxstyle="round,pad=0.42,rounding_size=0.55", facecolor=theme.background,
                           edgecolor=theme.amber, linewidth=0.9))
    footer_lines = [w for line in footer for w in textwrap.wrap(line, FOOTER_WIDTH)]
    rule_y = (0.22 + 0.145 * len(footer_lines)) / height
    fig.add_artist(plt.Line2D([edge, 1 - edge], [rule_y] * 2, color=theme.grid, linewidth=0.8,
                              transform=fig.transFigure))
    for i, line in enumerate(reversed(footer_lines)):
        fig.text(edge, (0.13 + 0.145 * i) / height, line, ha="left", va="bottom", fontsize=6.6, color=theme.faint)
    top = 1 - (1.0 + 0.17 * (len(sub_lines) - 1)) / height
    bottom = rule_y + axis_space / height
    return Frame(fig, top, bottom)


def headroom(ax, fraction: float = 0.35) -> None:
    """Extend the y-axis upward so a top legend sits above the data."""
    low, high = ax.get_ylim()
    ax.set_ylim(low, high + (high - low) * fraction)


def twin_axis(ax, theme: Theme, color: str):
    twin = ax.twinx()
    twin.grid(False)
    twin.tick_params(colors=theme.spine, labelcolor=color, labelsize=7.2)
    twin.spines["right"].set_visible(True)
    twin.spines["right"].set_color(theme.spine)
    return twin


def style_axes(ax, theme: Theme, grid: str = "y") -> None:
    ax.set_facecolor(theme.panel)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(theme.spine)
    if grid:
        ax.grid(True, axis=grid if grid in ("x", "y") else "both", color=theme.grid, linewidth=0.7)
    else:
        ax.grid(False)
    ax.tick_params(colors=theme.spine, labelcolor=theme.muted)


def bare_axes(ax, theme: Theme) -> None:
    ax.set_facecolor(theme.panel)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


def save_figure(fig: plt.Figure, directory: Path, stem: str, theme: Theme) -> Path:
    """Write <stem>-<theme>.png.

    The render is reduced to a 256-color palette without dithering: about 70% smaller
    and visually unchanged for flat chart colors. Both steps are deterministic, so a
    rerun with identical inputs writes identical bytes.
    """
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{stem}-{theme.name}.png"
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=EXPORT_DPI, facecolor=theme.background)
    plt.close(fig)
    buffer.seek(0)
    image = Image.open(buffer).convert("RGB")
    image.quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE).save(path, optimize=True)
    return path


def text_rows(ax, rows: List[Tuple[str, str]], theme: Theme, top: float = 0.97, step: float = 0.075,
              value_x: float = 0.98, label_x: float = 0.02, size: float = 8.1,
              value_colors: Optional[List[str]] = None) -> None:
    """Two-column label/value list with right-aligned (tabular) numbers."""
    for i, (label, value) in enumerate(rows):
        y = top - i * step
        ax.text(label_x, y, label, transform=ax.transAxes, ha="left", va="top", fontsize=size, color=theme.muted)
        color = value_colors[i] if value_colors else theme.text
        ax.text(value_x, y, value, transform=ax.transAxes, ha="right", va="top", fontsize=size,
                color=color, fontweight="semibold")
