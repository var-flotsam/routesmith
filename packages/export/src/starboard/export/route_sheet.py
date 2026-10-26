"""The printable driver route sheet: one section per truck, steps in order (HANDOFF §2.1).

Each truck's section opens on a new page with its totals and a drawing of its path,
then lists every step: what to do, on which street, how far, and the carts to collect.
A page the steps run on to repeats a small drawing of the path at its top. Every cart
is on the truck's right, so the sheet says so once rather than on every line. The type
is large enough to read in a cab, and each page's footer names the route, the truck
and the page, so a loose page finds its way back.

ReportLab (BSD, https://www.reportlab.com/opensource/) lays it out; its invariant mode
leaves out creation dates and random ids, so one run always gives the same bytes. Text
from the run goes into ReportLab's paragraph markup escaped, so a street named with `<`
or `&` prints as named. A table row may split across pages, so no step is too long to
print.

The sheet is set in DejaVu Sans (https://dejavu-fonts.github.io/), kept in `fonts/`
under its own licence, and embedded in the PDF as a subset of the letters it uses. PDF
viewers' built-in fonts stop at Western European letters; DejaVu Sans also covers the
rest of the Latin alphabets, Greek and Cyrillic, so Kalākaua Ave and Łódź Rd print as
named. A letter it lacks prints as an empty box, and the sheet still prints.
"""

import io
import math
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.graphics import renderPDF
from reportlab.graphics.shapes import Circle, Drawing, PolyLine, Rect
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase.pdfmetrics import registerFont, stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    NextPageTemplate,
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
_PAGE_WIDTH, _PAGE_HEIGHT = LETTER
_MARGIN = 0.6 * inch  # narrower than the usual inch, so the steps table has room
_PATH_DRAWING_SIZE = 3.5 * inch
# The path again, smaller, at the top of each page a truck's steps run on to.
_THUMBNAIL_SIZE = 1.4 * inch
_THUMBNAIL_BAND = _THUMBNAIL_SIZE + 0.2 * inch
_PATH_COLOUR = colors.HexColor("#2563eb")
_START_RADIUS = 4  # points; the yard, where the path starts and ends
# The steps table: step number, instruction, distance, carts; together the frame's width.
# The first is wide enough for a four-digit step number and the third for its heading,
# with the cell padding either side.
_COLUMN_WIDTHS = (0.65 * inch, 2.75 * inch, 1.1 * inch, 2.8 * inch)
# Long cart lists are cut on the sheet, and so are long stop ids; the CSV has them all.
_CARTS_SHOWN = 12
_STOP_ID_CHARACTERS_SHOWN = 24

_FONTS = Path(__file__).parent / "fonts"
_FONT, _BOLD_FONT = "DejaVuSans", "DejaVuSans-Bold"  # named as their files in `fonts/`
_SAMPLE_STYLES = getSampleStyleSheet()
_TITLE = ParagraphStyle("title", parent=_SAMPLE_STYLES["Title"], fontName=_BOLD_FONT)
# 13 point: larger than a document's usual 10, for reading at arm's length in a cab.
_STEP = ParagraphStyle(
    "step", parent=_SAMPLE_STYLES["Normal"], fontName=_FONT, fontSize=13, leading=16
)
_NOTE = ParagraphStyle(
    "note", parent=_SAMPLE_STYLES["Normal"], fontName=_FONT, fontSize=11, leading=14
)
_FOOTER_SIZE = 9


@cache
def _register_fonts() -> None:
    """Tell ReportLab where the sheet's fonts are, once, on the first sheet printed."""
    for name in (_FONT, _BOLD_FONT):
        registerFont(TTFont(name, str(_FONTS / f"{name}.ttf")))


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


def _shortened(text: str, characters: int) -> str:
    return text if len(text) <= characters else text[: characters - 1] + "…"


def _carts(step: Step) -> str:
    if not step.stop_ids:
        return ""
    shown = ", ".join(
        _shortened(stop_id, _STOP_ID_CHARACTERS_SHOWN) for stop_id in step.stop_ids[:_CARTS_SHOWN]
    )
    more = len(step.stop_ids) - _CARTS_SHOWN
    return f"{len(step.stop_ids)}: {shown}" + (f" and {more} more" if more > 0 else "")


def _fitted(text: str, width: float, font: str, size: float) -> str:
    """`text`, cut short with an ellipsis where it would print wider than `width`."""
    if stringWidth(text, font, size) <= width:
        return text
    while text and stringWidth(text + "…", font, size) > width:
        text = text[:-1]
    return text + "…"


def _text(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text), style)


def _path_drawing(route: TruckRoute, size: float) -> Drawing:
    """The route's path, north up, scaled to fit a square and centred, its start marked."""
    # The drawing holds no text, but ReportLab names a font for it all the same.
    drawing = Drawing(size, size, initialFontName=_FONT)
    frame = Rect(0, 0, size, size)
    frame.strokeColor, frame.fillColor = colors.lightgrey, None
    drawing.add(frame)
    if len(route.path) < 2:
        return drawing
    lats = [lat for _, lat in route.path]
    # A degree of longitude is cos(latitude) times as long as a degree of latitude.
    shrink = math.cos(math.radians((min(lats) + max(lats)) / 2))
    xs = [lon * shrink for lon, _ in route.path]
    west, south = min(xs), min(lats)
    width, height = max(xs) - west, max(lats) - south
    scale = (size * 0.9) / (max(width, height) or 1.0)
    left, bottom = (size - width * scale) / 2, (size - height * scale) / 2
    points: list[float] = []
    for x, lat in zip(xs, lats, strict=True):
        points += [left + (x - west) * scale, bottom + (lat - south) * scale]
    drawing.add(PolyLine(points, strokeColor=_PATH_COLOUR, strokeWidth=1.5))
    drawing.add(
        Circle(points[0], points[1], _START_RADIUS, fillColor=colors.black, strokeColor=None)
    )
    return drawing


@dataclass
class _Pages:
    """Draws what every page carries besides its steps: the footer, and on a page a truck's
    steps run on to, a heading and a small drawing of its path. `truck` is the truck whose
    section the page is in."""

    route_name: str
    routes: tuple[TruckRoute, ...]
    truck: int = 1
    thumbnails: dict[int, Drawing] = field(default_factory=dict)

    def continued(self, canvas: Canvas, document: BaseDocTemplate) -> None:
        top = _PAGE_HEIGHT - _MARGIN
        if self.truck not in self.thumbnails:
            self.thumbnails[self.truck] = _path_drawing(
                self.routes[self.truck - 1], _THUMBNAIL_SIZE
            )
        renderPDF.draw(
            self.thumbnails[self.truck],
            canvas,
            _PAGE_WIDTH - _MARGIN - _THUMBNAIL_SIZE,
            top - _THUMBNAIL_SIZE,
        )
        canvas.saveState()
        canvas.setFont(_BOLD_FONT, _STEP.fontSize)
        canvas.drawString(
            _MARGIN, top - _STEP.fontSize, f"Truck {self.truck} of {len(self.routes)}, continued"
        )
        canvas.restoreState()

    def footer(self, canvas: Canvas, document: BaseDocTemplate) -> None:
        y = _MARGIN / 2
        where = f"Truck {self.truck} of {len(self.routes)}, page {canvas.getPageNumber()}"
        room = _PAGE_WIDTH - 2 * _MARGIN - stringWidth(f"   {where}", _FONT, _FOOTER_SIZE)
        canvas.saveState()
        canvas.setFont(_FONT, _FOOTER_SIZE)
        canvas.drawString(_MARGIN, y, _fitted(self.route_name, room, _FONT, _FOOTER_SIZE))
        canvas.drawRightString(_PAGE_WIDTH - _MARGIN, y, where)
        canvas.restoreState()


class _TruckStart(Flowable):
    """Takes no room on the page; tells the page decorations a truck's section starts here."""

    def __init__(self, pages: _Pages, truck: int) -> None:
        super().__init__()
        self.pages, self.truck = pages, truck

    def wrap(self, available_width: float, available_height: float) -> tuple[float, float]:
        return 0, 0

    def draw(self) -> None:
        self.pages.truck = self.truck


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
    table = Table(rows, colWidths=list(_COLUMN_WIDTHS), repeatRows=1, splitInRow=1)
    table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -1), _FONT, _STEP.fontSize, _STEP.leading),
                ("FONT", (0, 0), (-1, 0), _BOLD_FONT, _STEP.fontSize, _STEP.leading),
                ("LINEBELOW", (0, 0), (-1, 0), 1, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.whitesmoke]),
            ]
        )
    )
    return table


def route_sheet_pdf(run: RunExport) -> bytes:
    """One section per truck, each starting on a new page, as US Letter."""
    _register_fonts()
    pages = _Pages(run.route_name, run.routes)
    story: list[Flowable] = []
    for number, route in enumerate(run.routes, start=1):
        if number > 1:
            story += [NextPageTemplate("first"), PageBreak()]
        story += [
            _TruckStart(pages, number),
            NextPageTemplate("continued"),
            _text(f"{run.route_name}: truck {number} of {len(run.routes)}", _TITLE),
            _text(
                f"{len(route.order)} stops, {distance(route.distance_m)}, "
                f"about {duration(route.route_time_s)}. Every cart is on your right.",
                _STEP,
            ),
            _text(
                "Streets © OpenStreetMap contributors, under the Open Database Licence "
                f"(openstreetmap.org/copyright), as of {run.osm_snapshot or 'a date not recorded'}."
                " The dot marks the yard, where the route starts and ends.",
                _NOTE,
            ),
            Spacer(1, 0.15 * inch),
            _path_drawing(route, _PATH_DRAWING_SIZE),
            Spacer(1, 0.15 * inch),
            _steps_table(route),
        ]
    width, height = _PAGE_WIDTH - 2 * _MARGIN, _PAGE_HEIGHT - 2 * _MARGIN
    first = Frame(_MARGIN, _MARGIN, width, height, id="first")
    continued = Frame(_MARGIN, _MARGIN, width, height - _THUMBNAIL_BAND, id="continued")
    buffer = io.BytesIO()
    document = BaseDocTemplate(
        buffer,
        pagesize=LETTER,
        pageTemplates=[
            PageTemplate(id="first", frames=[first], onPageEnd=pages.footer),
            PageTemplate(
                id="continued", frames=[continued], onPage=pages.continued, onPageEnd=pages.footer
            ),
        ],
        title=f"{run.route_name} route sheet",
        author="Starboard Routing",
        invariant=True,
        # ReportLab's canvas otherwise names Helvetica on every page, used or not.
        initialFontName=_FONT,
    )
    document.build(story)
    return buffer.getvalue()
