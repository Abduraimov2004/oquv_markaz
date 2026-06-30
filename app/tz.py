"""Jarayon vaqt zonasini Toshkentга (UTC+5) o'rnatadi.

Bu modul eng birinchi import qilinishi kerak — shunda barcha
datetime.now() / date.today() Toshkent vaqtini qaytaradi.
"""
import os
import time

os.environ["TZ"] = "Asia/Tashkent"
try:
    time.tzset()  # faqat Unix (server) da ishlaydi
except Exception:
    pass
