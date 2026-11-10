"""LinkedIn architecture GIF. Black ink on a white plan sheet."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 628
WHITE = (255, 255, 255)
INK = (17, 17, 17)
FONT = Path(r"C:\Windows\Fonts\segoeui.ttf")
FONT_B = Path(r"C:\Windows\Fonts\segoeuib.ttf")
OUT = Path(__file__).resolve().parents[1] / "docs" / "images" / "linkedin-architecture.gif"
DATA_OUT = OUT.with_name("linkedin-data-flow.gif")
FLOW_OUT = OUT.with_name("linkedin-workflow.gif")

SHEET = 22
LEFT = 48
RIGHT = W - 48
CONTENT_W = RIGHT - LEFT
TITLE_TOP = 508


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_B if bold else FONT), size)


def text_width(draw: ImageDraw.ImageDraw, text: str, face: ImageFont.FreeTypeFont) -> int:
    box = draw.textbbox((0, 0), text, font=face)
    return box[2] - box[0]


def center_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    face: ImageFont.FreeTypeFont,
    cx: float,
    y: float,
    fill: tuple[int, int, int],
) -> None:
    draw.text((cx - text_width(draw, text, face) / 2, y), text, font=face, fill=fill)


def arrow(draw: ImageDraw.ImageDraw, x1: int, x2: int, y: int, heavy: bool) -> None:
    width = 2 if heavy else 1
    draw.line((x1, y, x2 - 9, y), fill=INK, width=width)
    draw.line((x2 - 11, y - 5, x2 - 1, y), fill=INK, width=width)
    draw.line((x2 - 11, y + 5, x2 - 1, y), fill=INK, width=width)


def draw_row(
    draw: ImageDraw.ImageDraw,
    items: list[tuple[str, str]],
    y: int,
    box_h: int,
    gap: int,
    active: int | None,
) -> None:
    count = len(items)
    box_w = (CONTENT_W - (count - 1) * gap) // count
    title_f = font(15, bold=True)
    sub_f = font(12)
    x = LEFT
    for i, (title, sub) in enumerate(items):
        on = active == i
        draw.rectangle((x, y, x + box_w, y + box_h), fill=INK if on else WHITE, outline=INK, width=2 if on else 1)
        ink = WHITE if on else INK
        center_text(draw, title, title_f, x + box_w / 2, y + 32, ink)
        center_text(draw, sub, sub_f, x + box_w / 2, y + 58, ink)
        if i < count - 1:
            arrow(draw, x + box_w + 7, x + box_w + gap - 6, y + box_h // 2, heavy=active == i + 1)
        x += box_w + gap


def sheet(
    draw: ImageDraw.ImageDraw,
    line_a: str = "Public reviews become one page.",
    line_b: str = "Or nothing is published.",
    kind: str = "Architecture plan",
    sheet_no: str = "Sheet 01",
) -> None:
    draw.rectangle((SHEET, SHEET, W - SHEET, H - SHEET), outline=INK, width=1)
    draw.line((SHEET, TITLE_TOP, W - SHEET, TITLE_TOP), fill=INK, width=1)
    split = 860
    draw.line((split, TITLE_TOP, split, H - SHEET), fill=INK, width=1)
    draw.text((LEFT, TITLE_TOP + 18), line_a, font=font(18), fill=INK)
    draw.text((LEFT, TITLE_TOP + 44), line_b, font=font(18), fill=INK)
    draw.text((split + 24, TITLE_TOP + 16), "GROWW REVIEW AGENT", font=font(12, bold=True), fill=INK)
    draw.text((split + 24, TITLE_TOP + 38), kind, font=font(16), fill=INK)
    draw.text((split + 24, TITLE_TOP + 64), sheet_no, font=font(12), fill=INK)


def frame(weekly_i: int | None, support_i: int | None) -> Image.Image:
    image = Image.new("RGB", (W, H), WHITE)
    draw = ImageDraw.Draw(image)
    sheet(draw)

    draw.text((LEFT, 46), "01", font=font(13, bold=True), fill=INK)
    draw.text((LEFT + 28, 46), "WEEKLY NOTE", font=font(13, bold=True), fill=INK)
    draw_row(
        draw,
        [
            ("Play reviews", "public listing"),
            ("Clean and store", "names dropped"),
            ("Five themes", "grouped by math"),
            ("Real quotes", "cut, not written"),
            ("Seven checks", "pass or stop"),
            ("Doc and mail", "via connector"),
        ],
        y=76,
        box_h=100,
        gap=28,
        active=weekly_i,
    )
    draw.text((LEFT, 192), "A failed check publishes nothing.", font=font(14), fill=INK)

    draw.text((LEFT, 268), "02", font=font(13, bold=True), fill=INK)
    draw.text((LEFT + 28, 268), "SUPPORT DESK", font=font(13, bold=True), fill=INK)
    draw_row(
        draw,
        [
            ("Customer message", "one reply"),
            ("Three checks", "facts, pattern, advice"),
            ("Person approves", "exact text"),
            ("Mail draft", "never sends"),
        ],
        y=298,
        box_h=100,
        gap=36,
        active=support_i,
    )
    draw.text(
        (LEFT, 416),
        "Advice is refused. Google login stays in the connector.",
        font=font(14),
        fill=INK,
    )
    return image


def data_frame(top_i: int | None, bottom_i: int | None) -> Image.Image:
    image = Image.new("RGB", (W, H), WHITE)
    draw = ImageDraw.Draw(image)
    sheet(
        draw,
        line_a="Play listing to the Google Doc.",
        line_b="A failed gate never calls MCP.",
        kind="Data flow",
        sheet_no="Sheet 02",
    )

    draw.text((LEFT, 46), "01", font=font(13, bold=True), fill=INK)
    draw.text((LEFT + 28, 46), "INGEST AND GROUP", font=font(13, bold=True), fill=INK)
    draw_row(
        draw,
        [
            ("Fetch reviews", "google-play-scraper"),
            ("Scrub and store", "Python, SQLite"),
            ("Embed and cluster", "MiniLM, scikit-learn"),
            ("Name the themes", "Groq, LangChain"),
        ],
        y=76,
        box_h=100,
        gap=36,
        active=top_i,
    )
    draw.text(
        (LEFT, 192),
        "Names are dropped before SQLite. Groq does not cluster.",
        font=font(14),
        fill=INK,
    )

    draw.text((LEFT, 268), "02", font=font(13, bold=True), fill=INK)
    draw.text((LEFT + 28, 268), "WRITE AND PUBLISH", font=font(13, bold=True), fill=INK)
    draw_row(
        draw,
        [
            ("Cut the quotes", "Python"),
            ("Write the note", "Gemini, LangChain"),
            ("Seven gates", "Python"),
            ("Publish", "MCP, then Google"),
        ],
        y=298,
        box_h=100,
        gap=36,
        active=bottom_i,
    )
    draw.text(
        (LEFT, 416),
        "Quotes are cut in Python. FastAPI only serves the Next.js console.",
        font=font(14),
        fill=INK,
    )
    return image


def workflow_frame(step: int) -> Image.Image:
    """One row. Reviews in, a note out, or nothing published."""
    image = Image.new("RGB", (W, H), WHITE)
    draw = ImageDraw.Draw(image)
    center_text(draw, "GROWW REVIEW AGENT", font(13, bold=True), W / 2, 92, INK)
    center_text(draw, "Reviews in. A note out. Or nothing.", font(28, bold=True), W / 2, 122, INK)

    box_w, box_h, gap = 180, 100, 34
    half_w, half_h = 74, 56
    pub_w = 180
    nodes_w = box_w * 3 + half_w * 2 + pub_w + gap * 4
    cursor = (W - nodes_w) // 2
    y = 230
    mid = y + box_h // 2
    title_f = font(16, bold=True)
    sub_f = font(13)

    boxes = [
        ("Fetch reviews", "Play listing"),
        ("Clean store", "names removed"),
        ("Write the note", "real quotes"),
    ]
    box_x: list[int] = []
    for i, (title, sub) in enumerate(boxes):
        box_x.append(cursor)
        on = step == i
        draw.rectangle(
            (cursor, y, cursor + box_w, y + box_h),
            fill=INK if on else WHITE,
            outline=INK,
            width=2 if on else 1,
        )
        ink = WHITE if on else INK
        center_text(draw, title, title_f, cursor + box_w / 2, y + 30, ink)
        center_text(draw, sub, sub_f, cursor + box_w / 2, y + 56, ink)
        if i < 2:
            arrow(draw, cursor + box_w + 6, cursor + box_w + gap - 6, mid, heavy=step == i + 1)
        cursor += box_w + gap

    dia_cx = cursor + half_w
    arrow(draw, box_x[2] + box_w + 6, dia_cx - half_w - 4, mid, heavy=step == 3)
    points = [
        (dia_cx, mid - half_h),
        (dia_cx + half_w, mid),
        (dia_cx, mid + half_h),
        (dia_cx - half_w, mid),
    ]
    draw.polygon(points, fill=INK if step == 3 else WHITE)
    draw.line(points + [points[0]], fill=WHITE if step == 3 else INK, width=2)
    center_text(draw, "7 checks", font(14, bold=True), dia_cx, mid - 10, WHITE if step == 3 else INK)

    pub_x = dia_cx + half_w + gap
    arrow(draw, dia_cx + half_w + 6, pub_x - 6, mid, heavy=step == 4)
    pass_on = step == 4
    draw.rectangle(
        (pub_x, y, pub_x + pub_w, y + box_h),
        fill=INK if pass_on else WHITE,
        outline=INK,
        width=2 if pass_on else 1,
    )
    center_text(draw, "Doc and mail", title_f, pub_x + pub_w / 2, y + 30, WHITE if pass_on else INK)
    center_text(draw, "only if they pass", sub_f, pub_x + pub_w / 2, y + 56, WHITE if pass_on else INK)
    center_text(draw, "Pass", font(12, bold=True), (dia_cx + half_w + pub_x) / 2, mid - 28, INK)

    stop_w, stop_h = 180, 64
    stop_x = dia_cx - stop_w // 2
    stop_y = mid + half_h + 36
    fail_on = step == 5
    draw.line((dia_cx, mid + half_h + 2, dia_cx, stop_y - 8), fill=INK, width=2 if fail_on else 1)
    draw.polygon(
        [(dia_cx - 5, stop_y - 10), (dia_cx + 5, stop_y - 10), (dia_cx, stop_y - 2)],
        fill=INK,
    )
    draw.rectangle(
        (stop_x, stop_y, stop_x + stop_w, stop_y + stop_h),
        fill=INK if fail_on else WHITE,
        outline=INK,
        width=2 if fail_on else 1,
    )
    center_text(
        draw,
        "Publish nothing",
        title_f,
        dia_cx,
        stop_y + 20,
        WHITE if fail_on else INK,
    )
    draw.text((dia_cx + 12, (mid + half_h + stop_y) / 2 - 10), "Fail", font=font(12, bold=True), fill=INK)
    return image


def save_gif(frames: list[Image.Image], path: Path) -> None:
    base = frames[0].quantize(colors=16, method=Image.Quantize.MEDIANCUT)
    quantized = [item.quantize(colors=16, palette=base, dither=Image.Dither.NONE) for item in frames]
    path.parent.mkdir(parents=True, exist_ok=True)
    quantized[0].save(
        path,
        save_all=True,
        append_images=quantized[1:],
        duration=800,
        loop=0,
        optimize=True,
        disposal=2,
    )
    print(f"{path} {path.stat().st_size}")


def main() -> None:
    steps: list[tuple[int | None, int | None]] = [(i, None) for i in range(6)] + [
        (None, i) for i in range(4)
    ]
    frames = [frame(w, s) for w, s in steps]
    save_gif(frames, OUT)

    data_steps: list[tuple[int | None, int | None]] = [(i, None) for i in range(4)] + [
        (None, i) for i in range(4)
    ]
    data_frames = [data_frame(top, bottom) for top, bottom in data_steps]
    save_gif(data_frames, DATA_OUT)

    flow_frames = [workflow_frame(i) for i in range(6)]
    save_gif(flow_frames, FLOW_OUT)


if __name__ == "__main__":
    main()
