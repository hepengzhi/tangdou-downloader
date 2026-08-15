# -*- coding: utf-8 -*-
"""tdcore - 糖豆广场舞下载器核心逻辑包（与 GUI/CLI 分离的纯逻辑层）。"""

__version__ = "1.5.0"

from .api import (  # noqa: F401
    API_PLAY,
    API_RECOMMEND,
    HEADERS,
    HEADERS_DL,
    QUALITIES,
    extract_vid,
    sanitize,
    default_download_dir,
    find_ffmpeg,
    head_ok,
    resolve_qualities,
    get_video_url_html,
    get_video_info,
    get_related,
    get_video_info_share,
    _pick_quality_url,
    http_get_json,
)
from .download import (  # noqa: F401
    download,
    extract_mp3,
    clip_video,
    download_video,
    download_related,
)
from .search import (  # noqa: F401
    sogou_search,
    song_mode,
    search_all,
)
from . import bilibili  # noqa: F401
from . import updater  # noqa: F401
from .log import get_logger, setup_log_file  # noqa: F401

__all__ = [
    "API_PLAY", "API_RECOMMEND", "HEADERS", "HEADERS_DL", "QUALITIES",
    "extract_vid", "sanitize", "default_download_dir", "find_ffmpeg",
    "head_ok", "resolve_qualities", "get_video_url_html", "get_video_info",
    "get_related", "get_video_info_share", "_pick_quality_url", "http_get_json",
    "download", "extract_mp3", "clip_video", "download_video", "download_related",
    "sogou_search", "song_mode", "search_all", "bilibili", "updater",
    "get_logger", "setup_log_file",
]
