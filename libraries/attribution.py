"""Attribution used by images derived from the upstream maimaidx project."""

from typing import TYPE_CHECKING, Optional

from .maimaidx_types import SourceName, source_label

if TYPE_CHECKING:
    from .image import DrawText


# ``design.png`` is a 1000px-wide footer strip.  Its arrows and border occupy
# the outer part of the strip, leaving about 840px for text after a small
# visual margin.  Keep this limit independent from the canvas width so a
# 1200px play card and a 1400px score table use the same safe inner area.
DEFAULT_ATTRIBUTION_MAX_WIDTH = 840


def attribution_text(source: SourceName | str = "lxns") -> str:
    if source == "merged":
        data_source = "LXNS & Diving-Fish"
    else:
        data_source = source_label(source if source in {"lxns", "diving-fish"} else "lxns")
    return (
        "Designed by Yuri-YuzuChaN & BlueDeer233. "
        f"Adapted by Amia_晓山瑞希. Data from {data_source}."
    )


def draw_attribution(
    drawer: "DrawText",
    width: int,
    y: int,
    source: SourceName | str = "lxns",
    color=(124, 129, 255, 255),
    max_width: Optional[int] = None,
) -> None:
    """Draw the complete credit inside the footer strip.

    ``width`` is the full canvas width, not the width of the decorative
    footer.  The previous implementation used ``width - 40`` as the text
    limit, which let the credit cross the footer's arrow/border artwork on
    the 1200px play card.  Keep the full attribution and shrink the font to
    the safe inner width instead of truncating it.
    """
    text = attribution_text(source)
    safe_width = min(
        max(1, int(width) - 40),
        int(max_width) if max_width is not None else DEFAULT_ATTRIBUTION_MAX_WIDTH,
    )
    size = 24
    while size > 12 and drawer.get_box(text, size)[2] > safe_width:
        size -= 1
    drawer.draw(width // 2, y, size, text, color, "mm")
