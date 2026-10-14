"""W9: proof.svg (one card per closed phase) and BADGE.md (the README line that shows it). Stdlib only."""
from html import escape as _esc

def escape(s):  # W47: xml.sax.saxutils drags in urllib.request (0.2 s); same &, <, > escaping
    return _esc(s, quote=False)

W, H = 600, 200
IMG = "proof.svg"


def _line(y: int, text: str, size: int = 16, weight: str = "normal") -> str:
    return (f'<text x="24" y="{y}" font-family="Helvetica, Arial, sans-serif" font-size="{size}" '
            f'font-weight="{weight}" fill="#1f2328">{escape(text)}</text>')


def svg(project: str, phase_id: str, title: str, merged: int, total: int, verified: int, cost: float,
        date: str) -> str:
    """The phase card: a 600x200 light card with dark text. Every text value is escaped, so a title with < or &
    still gives valid XML. No outcome word: the run has not ended when a phase closes."""
    rows = [
        _line(44, project, 18, "bold"),
        _line(76, f"{phase_id} {title}", 16, "bold"),
        _line(108, f"tasks merged {merged} of {total}  ·  verified {verified}"),
        _line(138, f"cost ${cost:.2f}"),
        _line(176, date, 13),
    ]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
            f'role="img" aria-label="{escape(f"{phase_id} proof")}">\n'
            f'<rect x="0" y="0" width="{W}" height="{H}" rx="10" fill="#f6f8fa" stroke="#d0d7de"/>\n'
            + "\n".join(rows) + "\n</svg>\n")


def badge(phase_id: str) -> str:
    """One markdown image line for the phase folder, plus one README-ready line with the path to the card."""
    path = f".agent/history/{phase_id}/{IMG}"
    return f"![Built by Autopilot]({IMG})\n\nREADME path (repo-relative): {path}\n"
