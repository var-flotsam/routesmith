"""The printable driver route sheet: one section per truck, steps in order (HANDOFF §2.1).

Each truck's section opens on a new page with its totals and a drawing of its path,
then lists every step: what to do, on which street, how far, and the carts to collect.
Every cart is on the truck's right, so the sheet says so once rather than on every line.
The type is large enough to read in a cab, and each page's footer names the route, the
truck and the page, so a loose page finds its way back.

ReportLab (BSD, https://www.reportlab.com/opensource/) lays it out; its invariant mode
leaves out creation dates and random ids, so one run always gives the same bytes. Text
from the run goes into ReportLab's paragraph markup escaped, so a street named with `<`
or `&` prints as named.
"""

import io
import math
from dataclasses import dataclass
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Circle, Drawing, PolyLine, Rect
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from starboard.export.model import RunExport, Step, TruckRoute

_SECONDS_PER_MINUTE = 60
_MINUTES_PER_HOUR = 60
_METRES_PER_KM = 1000
_MARGIN = 0.6 * inch  # narrower than the usual inch, so the steps table has room
_PATH_DRAWING_SIZE = 3.5 * inch
_PATH_COLOUR = colors.HexColor("#2563eb")
_START_RADIUS = 4  # points; the yard, where the path starts and ends
# The steps table: step number, instruction, distance, carts; together the frame's width.
_COLUMN_WIDTHS = (0.5 * inch, 3.0 * inch, 1.0 * inch, 2.8 * inch)
# Long cart lists are cut on the sheet; the CSV has every stop.
_CARTS_SHOWN = 12

_SAMPLE_STYLES = getSampleStyleSheet()
_TITLE = ParagraphStyle("title", parent=_SAMPLE_STYLES["Title"])
# 13 point: larger than a document's usual 10, for reading at arm's length in a cab.
_STEP = ParagraphStyle("step", parent=_SAMPLE_STYLES["Normal"], fontSize=13, leading=16)
_NOTE = ParagraphStyle("note", parent=_SAMPLE_STYLES["Normal"], fontSize=11, leading=14)
_FOOTER_FONT = ("Helvetica", 9)


def instruction(step: Step) -> str:
    """The step as the driver reads it."""
    street = step.street or "the unnamed road"
    return {
        "depart": f"Leave onto {street}",
        "left": f"Turn left onto {street}",
        "right": f"Turn right onto {street}",
        "straight": f"Continue onto {street}",
        "u_turn": f"Make a U-turn on {street}",
        "unload": "Unload at the disposal site",
        "arrive": "Return to the yard",
    }.get(step.action, step.action)


def distance(metres: float) -> str:
    """Metres under a kilometre, kilometres to one decimal place above it."""
    if metres < _METRES_PER_KM:
        return f"{metres:,.0f} m"
    return f"{metres / _METRES_PER_KM:,.1f} km"


def duration(seconds: float) -> str:
    """Hours and minutes, to the nearest minute."""
    hours, minutes = divmod(round(seconds / _SECONDS_PER_MINUTE), _MINUTES_PER_HOUR)
    return f"{hours} h {minutes:02d} min" if hours else f"{minutes} min"


def _carts(step: Step) -> str:
    if not step.stop_ids:
        return ""
    shown = ", ".join(step.stop_ids[:_CARTS_SHOWN])
    more = len(step.stop_ids) - _CARTS_SHOWN
    return f"{len(step.stop_ids)}: {shown}" + (f" and {more} more" if more > 0 else "")


def _text(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text), style)


def _path_drawing(route: TruckRoute) -> Drawing:
    """The route's path, north up, scaled to fit a square and centred, its start marked."""
    size = _PATH_DRAWING_SIZE
    drawing = Drawing(size, size)
    frame = Rect(0, 0, size, size)
    frame.strokeColor, frame.fillColor = colors.lightgrey, None
    drawing.add(frame)
    if len(route.path) < 2:
        return drawing
    lats = [lat for _, lat in route.path]
    # A degree of longitude is cos(latitude) times as long as a degree of latitude.
    shrink = math.cos(math.radians((min(lats) + max(lats)) / 2))
    xs = [lon * shrink for lon, _ in route.path]
    width, height = max(xs) - min(xs), max(lats) - min(lats)
    scale = (size * 0.9) / (max(width, height) or 1.0)
    left, bottom = (size - width * scale) / 2, (size - height * scale) / 2
    points: list[float] = []
    for x, lat in zip(xs, lats, strict=True):
        points += [left + (x - min(xs)) * scale, bottom + (lat - min(lats)) * scale]
    drawing.add(PolyLine(points, strokeColor=_PATH_COLOUR, strokeWidth=1.5))
    drawing.add(
        Circle(points[0], points[1], _START_RADIUS, fillColor=colors.black, strokeColor=None)
    )
    return drawing


@dataclass
class _Footer:
    """Draws each page's footer; `truck` is the truck whose section the page is in."""

    route_name: str
    trucks: int
    truck: int = 1

    def __call__(self, canvas: Canvas, document: BaseDocTemplate) -> None:
        canvas.saveState()
        canvas.setFont(*_FOOTER_FONT)
        canvas.drawString(
            _MARGIN,
            _MARGIN / 2,
            f"{self.route_name}, truck {self.truck} of {self.trucks}, "
            f"page {canvas.getPageNumber()}",
        )
        canvas.restoreState()


class _TruckStart(Flowable):
    """Takes no room on the page; tells the footer that a truck's section starts here."""

    def __init__(self, footer: _Footer, truck: int) -> None:
        super().__init__()
        self.footer, self.truck = footer, truck

    def wrap(self, available_width: float, available_height: float) -> tuple[float, float]:
        return 0, 0

    def draw(self) -> None:
        self.footer.truck = self.truck


def _steps_table(route: TruckRoute) -> Table:
    rows: list[list[str | Paragraph]] = [["#", "Do this", "Distance", "Carts"]]
    rows += [
        [
            str(k),
            _text(instruction(step), _STEP),
            distance(step.distance_m) if step.distance_m else "",
            _text(_carts(step), _STEP),
        ]
        for k, step in enumerate(route.steps, start=1)
    ]
    table = Table(rows, colWidths=list(_COLUMN_WIDTHS), repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -1), "Helvetica", _STEP.fontSize, _STEP.leading),
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", _STEP.fontSize, _STEP.leading),
                ("LINEBELOW", (0, 0), (-1, 0), 1, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.whitesmoke]),
            ]
        )
    )
    return table


def route_sheet_pdf(run: RunExport) -> bytes:
    """One section per truck, each starting on a new page, as US Letter."""
    footer = _Footer(run.route_name, len(run.routes))
    story: list[Flowable] = []
    for number, route in enumerate(run.routes, start=1):
        if number > 1:
            story.append(PageBreak())
        story += [
            _TruckStart(footer, number),
            _text(f"{run.route_name}: truck {number} of {len(run.routes)}", _TITLE),
            _text(
                f"{len(route.order)} stops, {distance(route.distance_m)}, "
                f"about {duration(route.route_time_s)}. Every cart is on your right.",
                _STEP,
            ),
            _text(
                f"Street data from OpenStreetMap ({run.osm_snapshot or 'date not recorded'}). "
                "The dot marks the yard, where the route starts and ends.",
                _NOTE,
            ),
            Spacer(1, 0.15 * inch),
            _path_drawing(route),
            Spacer(1, 0.15 * inch),
            _steps_table(route),
        ]
    buffer = io.BytesIO()
    width, height = LETTER
    frame = Frame(_MARGIN, _MARGIN, width - 2 * _MARGIN, height - 2 * _MARGIN, id="sheet")
    document = BaseDocTemplate(
        buffer,
        pagesize=LETTER,
        pageTemplates=[PageTemplate(id="sheet", frames=[frame], onPageEnd=footer)],
        title=f"{run.route_name} route sheet",
        author="Starboard Routing",
        invariant=True,
    )
    document.build(story)
    return buffer.getvalue()
