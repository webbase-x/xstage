"""Shared compact operator-overlay geometry; singer output stays independent."""

def lyric_font_size(preferred, width, height):
    return max(20, min(round(int(preferred)*height/1080), width//14))


def lyric_top(height, band_height, line_height, gap, reserved_top, reserved_bottom, idle=False):
    target = height*.40 if idle else height-band_height-reserved_bottom-line_height-gap
    return max(reserved_top, min(target, height-band_height-16))

def overlay_layout(width, height, search_row_height=32):
    width, height = max(360, int(width)), max(400, int(height))
    margin = 12 if width < 1000 else 24
    top = 132 if height < 650 else 174
    row_height = max(32, int(search_row_height))
    # Keep the operator overlay clear of the lyric band, even at 800x500.
    # Five rows is the target; only compact/high-DPI viewports reduce it.
    overhead, lyric_reserve = 166, 136
    search_top = max(100, min(top, height-lyric_reserve-overhead-5*row_height))
    rows = max(1, min(5, (height-lyric_reserve-search_top-overhead)//row_height))
    search_height = overhead + rows*row_height
    return {
        'search': (margin, search_top, width-2*margin, search_height),
        'queue': (margin, top, width-2*margin, 218),
        'rows': rows,
        'query_width': max(220, min(480, round(width*.40))),
    }
