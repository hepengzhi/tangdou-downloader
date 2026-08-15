# -*- coding: utf-8 -*-
"""日志落盘：RotatingFileHandler 写到 %LOCALAPPDATA%/TangdouDownloader/logs/。"""
import logging
import os
from logging.handlers import RotatingFileHandler

LOGGER_NAME = "tangdou"


def log_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".tangdou-downloader")
    return os.path.join(base, "TangdouDownloader", "logs")


def get_logger():
    return logging.getLogger(LOGGER_NAME)


def setup_log_file():
    """初始化文件日志（幂等）。返回 logger。"""
    lg = logging.getLogger(LOGGER_NAME)
    if lg.handlers:
        return lg
    d = log_dir()
    try:
        os.makedirs(d, exist_ok=True)
        fh = RotatingFileHandler(
            os.path.join(d, "tangdou.log"),
            maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8",
        )
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        lg.addHandler(fh)
        lg.setLevel(logging.INFO)
    except Exception:
        pass  # 日志失败不影响主功能
    return lg
