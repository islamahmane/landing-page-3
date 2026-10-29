# -*- coding: utf-8 -*-
"""
خادم صفحة هبوط الأساور المخصصة
- يعرض الصفحة (index.html)
- يستقبل الطلب من النموذج ويرسله إلى بوت تيليغرام (مع الصورة إن وُجدت)
"""

import os
import re
import time
from collections import defaultdict, deque
from html import escape

import requests
from flask import Flask, jsonify, request, send_from_directory

# ======================================================================
#  >>>>>>>>>>>>>>>>>>>>   إعدادات تيليغرام (عدّل هنا فقط)   <<<<<<<<<<<<<<<<<<<<
# ======================================================================
#  1) BOT_TOKEN : الرمز السري للبوت (تحصل عليه من @BotFather)
#     مثال: 123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
#  2) CHAT_ID   : معرّف الحساب أو المجموعة التي ستصلها الطلبات
#     (تحصل عليه مثلاً من بوت @userinfobot أو @RawDataBot)
#
#  ملاحظة: لا تشارك هذا الملف مع أحد بعد وضع التوكن فيه.
#  يمكنك أيضاً وضعهما كمتغيرات بيئة بنفس الاسمين بدل كتابتهما هنا.
# ----------------------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "ضع_التوكن_السري_هنا")
CHAT_ID = os.getenv("CHAT_ID", "ضع_معرف_الدردشة_هنا")
# ======================================================================

# الأسعار بالدينار الجزائري
BRACELET_PRICE = 1850
DELIVERY_PRICES = {
    "office": 350,  # توصيل للمكتب
    "home": 650,    # توصيل للمنزل
}
DELIVERY_LABELS = {"office": "المكتب", "home": "المنزل"}

WILAYAS = [
    "أدرار", "الشلف", "الأغواط", "أم البواقي", "باتنة", "بجاية", "بسكرة", "بشار",
    "البليدة", "البويرة", "تمنراست", "تبسة", "تلمسان", "تيارت", "تيزي وزو", "الجزائر",
    "الجلفة", "جيجل", "سطيف", "سعيدة", "سكيكدة", "سيدي بلعباس", "عنابة", "قالمة",
    "قسنطينة", "المدية", "مستغانم", "المسيلة", "معسكر", "ورقلة", "وهران", "البيض",
    "إليزي", "برج بوعريريج", "بومرداس", "الطارف", "تندوف", "تيسمسيلت", "الوادي",
    "خنشلة", "سوق أهراس", "تيبازة", "ميلة", "عين الدفلى", "النعامة", "عين تموشنت",
    "غرداية", "غليزان", "تيميمون", "برج باجي مختار", "أولاد جلال", "بني عباس",
    "عين صالح", "عين قزام", "تقرت", "جانت", "المغير", "المنيعة",
]
VALID_WILAYAS = {f"{i:02d} - {name}" for i, name in enumerate(WILAYAS, start=1)}

ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "webp"}
MAX_UPLOAD_MB = 8

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=os.path.join(BASE_DIR, "static"), static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

# ---------------------------------------------------------------- حماية بسيطة من الإزعاج
_hits = defaultdict(deque)


def too_many_requests(ip, limit=5, window=600):
    """يسمح بـ 5 طلبات كل 10 دقائق لكل عنوان IP."""
    now = time.time()
    q = _hits[ip]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(now)
    return False


def client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    return (forwarded.split(",")[0].strip() if forwarded else request.remote_addr) or "unknown"


# ---------------------------------------------------------------- تيليغرام
def telegram_call(method, data=None, files=None):
    """يرسل طلباً لواجهة تيليغرام. يعيد True عند النجاح."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        r = requests.post(url, data=data, files=files, timeout=30)
        return r.ok
    except requests.RequestException:
        return False


def telegram_configured():
    return not (BOT_TOKEN.startswith("ضع_") or CHAT_ID.startswith("ضع_"))


# ---------------------------------------------------------------- المسارات
@app.route("/")
def home():
    return send_from_directory(BASE_DIR, "index.html")


@app.errorhandler(413)
def too_large(_e):
    return jsonify(ok=False, message=f"حجم الصورة كبير جداً (الحد الأقصى {MAX_UPLOAD_MB} ميغابايت)."), 413


@app.route("/order", methods=["POST"])
def order():
    # حقل فخ للروبوتات (يبقى فارغاً عند البشر)
    if request.form.get("website"):
        return jsonify(ok=True, message="تم استلام طلبك.")

    if too_many_requests(client_ip()):
        return jsonify(ok=False, message="محاولات كثيرة، أعد المحاولة بعد قليل."), 429

    if not telegram_configured():
        return jsonify(ok=False, message="الخادم غير مُعدّ بعد (التوكن أو معرّف الدردشة مفقود)."), 500

    first_name = request.form.get("first_name", "").strip()
    last_name = request.form.get("last_name", "").strip()
    phone = re.sub(r"[\s\-.]", "", request.form.get("phone", ""))
    wilaya = request.form.get("wilaya", "").strip()
    commune = request.form.get("commune", "").strip()
    delivery = request.form.get("delivery", "").strip()
    custom_type = request.form.get("custom_type", "none").strip()
    custom_text = request.form.get("custom_text", "").strip()
    image = request.files.get("custom_image")

    # ---- التحقق من البيانات
    if not (2 <= len(first_name) <= 40) or not (2 <= len(last_name) <= 40):
        return jsonify(ok=False, message="الرجاء كتابة الاسم واللقب بشكل صحيح."), 400
    if not re.fullmatch(r"(?:\+213|0)[567]\d{8}", phone):
        return jsonify(ok=False, message="رقم الهاتف غير صحيح (مثال: 0555123456)."), 400
    if wilaya not in VALID_WILAYAS:
        return jsonify(ok=False, message="الرجاء اختيار الولاية."), 400
    if not (2 <= len(commune) <= 60):
        return jsonify(ok=False, message="الرجاء كتابة البلدية."), 400
    if delivery not in DELIVERY_PRICES:
        return jsonify(ok=False, message="الرجاء اختيار نوع التوصيل."), 400

    image_bytes, image_ext, image_mime = None, None, None
    if custom_type == "text":
        if len(custom_text) > 60:
            return jsonify(ok=False, message="الكلمة طويلة جداً (الحد الأقصى 60 حرفاً)."), 400
    elif custom_type == "image":
        if not image or not image.filename:
            return jsonify(ok=False, message="الرجاء اختيار صورة أو تغيير خيار التخصيص."), 400
        image_ext = image.filename.rsplit(".", 1)[-1].lower() if "." in image.filename else ""
        if image_ext not in ALLOWED_IMAGE_EXT or not (image.mimetype or "").startswith("image/"):
            return jsonify(ok=False, message="الصورة يجب أن تكون بصيغة JPG أو PNG أو WEBP."), 400
        image_bytes = image.read()
        image_mime = image.mimetype
    else:
        custom_type = "none"

    # ---- حساب السعر في الخادم (لا نثق بالسعر القادم من المتصفح)
    delivery_price = DELIVERY_PRICES[delivery]
    total = BRACELET_PRICE + delivery_price
    ref = time.strftime("%d%H%M%S")

    if custom_type == "text":
        custom_line = f"✍️ الكلمة المطلوبة: <b>{escape(custom_text) if custom_text else '—'}</b>"
    elif custom_type == "image":
        custom_line = "🖼 الصورة المطلوبة: مرفقة في الرسالة التالية"
    else:
        custom_line = "📝 التخصيص: لم يحدده الزبون (يرجى التواصل معه)"

    message = (
        f"🛍 <b>طلب جديد #{ref}</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"👤 الاسم: {escape(first_name)} {escape(last_name)}\n"
        f"📞 الهاتف: <code>{escape(phone)}</code>\n"
        f"📍 الولاية: {escape(wilaya)}\n"
        f"🏘 البلدية: {escape(commune)}\n"
        f"🚚 التوصيل إلى: {DELIVERY_LABELS[delivery]}\n"
        f"━━━━━━━━━━━━━━\n"
        f"{custom_line}\n"
        f"━━━━━━━━━━━━━━\n"
        f"💍 السوار: {BRACELET_PRICE} دج\n"
        f"🚚 التوصيل: {delivery_price} دج\n"
        f"💰 <b>المجموع: {total} دج</b>"
    )

    if not telegram_call("sendMessage", data={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}):
        return jsonify(ok=False, message="تعذّر إرسال الطلب، أعد المحاولة بعد قليل."), 502

    # الصورة تُرسل كملف (document) للحفاظ على جودتها الأصلية
    if image_bytes:
        telegram_call(
            "sendDocument",
            data={"chat_id": CHAT_ID, "caption": f"صورة الطلب #{ref} - {first_name} {last_name} - {phone}"},
            files={"document": (f"order_{ref}.{image_ext}", image_bytes, image_mime)},
        )

    return jsonify(ok=True, message="تم استلام طلبك بنجاح ✅ سنتصل بك قريباً لتأكيد الطلب.")


if __name__ == "__main__":
    # للتجربة المحلية: python app.py ثم افتح http://127.0.0.1:5000
    # على الاستضافة استعمل: gunicorn app:app
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
