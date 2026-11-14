"""Shared compact operator-overlay geometry; singer output stays independent."""

def lyric_font_size(preferred, width, height):
    return max(20, min(round(int(preferred)*height/1080), width//14))


def lyric_top(height, band_height, line_height, gap, reserved_top, reserved_bottom, idle=False):
    target = height*.40 if idle else height-band_height-reserved_bottom-line_height-gap
    return max(reserved_top, min(target, height-band_height-16))

def overlay_layout(width, height):
    width, height = max(360, int(width)), max(400, int(height))
    margin = 12 if width < 1000 else 24
    rows = 1 if height < 650 else 3 if height < 900 else 4
    top = 132 if height < 650 else 174
    search_height = 166 + rows * 32
    return {
        'search': (margin, top, width-2*margin, search_height),
        'queue': (margin, top, width-2*margin, 218),
        'rows': rows,
        'query_width': max(220, min(480, round(width*.40))),
    }
