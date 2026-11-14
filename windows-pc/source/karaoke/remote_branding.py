"""Small same-origin logo using the supplied desktop branding asset."""
from functools import lru_cache
from io import BytesIO
from PIL import Image
from .branding import asset

@lru_cache(maxsize=1)
def mobile_logo():
    with Image.open(asset('xstage-logo.jpg')) as source:
        image=source.convert('RGB')
        image.thumbnail((384,384),Image.Resampling.LANCZOS)
        output=BytesIO()
        image.save(output,format='JPEG',quality=88,optimize=True)
        return output.getvalue()
