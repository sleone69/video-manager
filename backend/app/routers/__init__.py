from .uploads import router as uploads_router
from .videos import router as videos_router
from .stars import router as stars_router
from .embed import router as embed_router

__all__ = ["uploads_router", "videos_router", "stars_router", "embed_router"]
