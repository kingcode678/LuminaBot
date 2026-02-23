import firebase_admin
from firebase_admin import credentials, firestore
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.request import HTTPXRequest
from datetime import datetime
import re
import sys
import easyocr
import os
import random
import string

# ========================
# 🔹 BOT TOKEN
# ========================
TOKEN = "8413147994:AAHoIHNvMdqmwMcRO8p_TyK46OAUuwv7SY4"
if not TOKEN or TOKEN == "YOUR_TOKEN_HERE":
    print("❌ Bot token təyin edilməyib!")
    sys.exit(1)

# ========================
# 🔹 KURS MƏLUMATLARI
# ========================
COURSES = {
    "frontend": {"name": "🎨 Frontend Development", "price": 12, "db_name": "frontend"},
    "ai": {"name": "🤖 Süni İntellekt (AI)", "price": 20, "db_name": "ai-python"}
}

# ========================
# 🔹 ADMIN MƏLUMATLARI
# ========================
ADMIN_PASSWORD = "sam3639mika"
admin_sessions = {}  # user_id: True (parol daxil edilib)

# ========================
# 🔹 FIREBASE
# ========================
try:
    firebase_admin.get_app()
except ValueError:
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)

db = firestore.client()

# ========================
# 🔹 USER DATA
# ========================
user_data = {}

# ========================
# 🔹 OCR
# ========================
reader = easyocr.Reader(['en', 'az'])

async def read_image_with_easyocr(file_path):
    results = reader.readtext(file_path, detail=0)
    return "\n".join(results)

# ========================
# 🔹 UTILITIES
# ========================
def generate_unique_code(length=6):
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
        docs = db.collection("affiliates").where("promoCode", "==", code).stream()
        if not any(docs):
            return code

def check_payment_keywords(text):
    """
    Çekdə ödənişə dair açar sözləri yoxlayır.
    Ən azı bir söz tapılsa True qaytarır.
    """
    text_lower = text.lower()
    
    # Axtarılan açar sözlər
    keywords = [
        "ödəniş", "odeme", "ödənilib", "odenilib",
        "uğurlu", "ugurlu", "uğurlu oldu", "ugurlu oldu",
        "təsdiq", "tesdiq", "təsdiqləndi", "tesdiqlendi",
        "aparıldı", "aparildi", "yerinə yetirildi", "yerine yetirildi",
        "completed", "success", "successful",
        "azn", "manat", "₼"
    ]
    
    # Rəqəm yoxlaması (məbləğ olmalıdır)
    has_amount = bool(re.search(r'\d+(\.\d{1,2})?', text_lower))
    
    # Açar sözlərdən ən azı biri varmı?
    has_keyword = any(keyword in text_lower for keyword in keywords)
    
    # Həm məbləğ, həm də açar söz olmalıdır
    return has_amount and has_keyword

# ========================
# 🔹 YARDIMCI FUNKSİYA: Email + Promo kod istifadə yoxlanışı
# ========================
async def check_email_promo_usage(email, promo_code):
    """
    Email + Promo kod kombinasiyası əvvəl istifadə edilibmi yoxlayır
    """
    payments = db.collection("payments").where("email", "==", email).where("affiliateCode", "==", promo_code).limit(1).stream()
    return any(payments)

# ========================
# 🔹 AFFILIATE REGISTER (HƏR AD ÜÇÜN YENİ KOD)
# ========================
async def affiliate_register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    name = " ".join(context.args)

    if not name:
        await update.message.reply_text("İstifadə: /affilatelumina Ad\n\nMəsələn: /affilatelumina Ali Veliyev")
        return

    # AD ilə yoxlanış - HƏR FƏRQLİ AD ÜÇÜN YENİ KOD
    docs = db.collection("affiliates").where("name", "==", name).limit(1).stream()
    existing = None
    
    for doc in docs:
        existing = doc
        break
    
    if existing:
        # Eyni ad artıq var, mövcud kodu göstər
        data = existing.to_dict()
        await update.message.reply_text(
            f"⚠️ Bu ad artıq qeydiyyatdan keçib!\n\n"
            f"👤 Ad: {data['name']}\n"
            f"🎫 Promo kodunuz: `{data['promoCode']}`\n"
            f"💰 Qazanc: {data.get('earned', 0):.2f} AZN\n"
            f"📊 Toplam satış: {data.get('totalSales', 0):.2f} AZN",
            parse_mode="Markdown"
        )
        return

    # YENİ AD ÜÇÜN YENİ KOD YARAT
    promo_code = generate_unique_code(6)

    db.collection("affiliates").add({
        "telegramId": user_id,
        "name": name,
        "promoCode": promo_code,
        "earned": 0,
        "totalSales": 0,
        "registeredAt": datetime.utcnow()
    })

    await update.message.reply_text(
        f"✅ Qeydiyyat tamamlandı!\n\n"
        f"👤 Ad: {name}\n"
        f"🎫 Promo kodunuz: `{promo_code}`\n\n"
        f"💡 Bu kod istifadə ediləndə alıcıya 10% endirim tətbiq olunacaq "
        f"və siz həmin satışdan 30% qazanacaqsınız.",
        parse_mode="Markdown"
    )

# ========================
# 🔹 SATIŞ (SPESIFIK PROMO KOD ÜÇÜN) - MÜTLƏQ TARİXCƏ GÖSTƏR
# ========================
async def show_sales(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("İstifadə: /satis PROMOKOD\n\nMəsələn: /satis ABC123")
        return

    promo_code = context.args[0].upper()
    
    # Affiliate tapılması
    affiliate_docs = db.collection("affiliates").where("promoCode", "==", promo_code).limit(1).stream()
    affiliate = None
    affiliate_data = None
    
    for doc in affiliate_docs:
        affiliate = doc
        affiliate_data = doc.to_dict()
        break
    
    # Əgər affiliate tapılmasa belə, boş tarixcə göstər (amma xəta da verə bilər)
    if not affiliate:
        # Yenə də tarixcə yarat, amma ad "Naməlum" olsun
        affiliate_name = "Naməlum"
        total_earned = 0
        total_sales = 0
    else:
        affiliate_name = affiliate_data['name']
        total_earned = affiliate_data.get('earned', 0)
        total_sales = affiliate_data.get('totalSales', 0)
    
    # Bu promo kod ilə edilmiş ödənişlər
    try:
        payments = db.collection("payments").where("affiliateCode", "==", promo_code).order_by("date", direction=firestore.Query.DESCENDING).stream()
        payments_list = list(payments)
    except Exception as e:
        payments_list = []
    
    # MÜTLƏQ TARİXCƏ GÖSTƏR (HƏTTA BOŞ OLSA BELƏ)
    text = f"📊 {affiliate_name} - `{promo_code}`\n\n"
    text += "📜 Satış Tarixcəsi:\n"
    
    if not payments_list:
        text += "Hələ satış yoxdur.\n\n"
    else:
        text += "\n"
        current_total = 0
        current_earned = 0
        
        for idx, payment_doc in enumerate(payments_list, 1):
            p = payment_doc.to_dict()
            date = p.get("date", datetime.utcnow())
            if isinstance(date, datetime):
                date_str = date.strftime("%d.%m.%Y %H:%M")
            else:
                date_str = str(date)
            
            price = p.get("finalPrice", 0)
            course = p.get("course", "naməlum")
            email = p.get("email", "naməlum")
            
            # Affiliate qazancı (30%)
            earned = price * 0.3
            
            current_total += price
            current_earned += earned
            
            text += f"{idx}. 📅 {date_str}\n"
            text += f"   📧 {email}\n"
            text += f"   📚 {COURSES.get(course, {}).get('name', course)}\n"
            text += f"   💰 {price:.2f} AZN (Sizin qazanc: {earned:.2f} AZN)\n\n"
        
        # Hesablanmış dəyərləri Firebase-dəki ilə sinxronlaşdır
        total_sales = current_total
        total_earned = current_earned
    
    # ÜMUMI STATISTIKA (HƏTTA 0 OLSA BELƏ)
    text += f"📈 Ümumi Statistika:\n"
    text += f"   💵 Toplam satış: {total_sales:.2f} AZN\n"
    text += f"   🎯 Sizin qazanc (30%): {total_earned:.2f} AZN"
    
    await update.message.reply_text(text, parse_mode="Markdown")

# ========================
# 🔹 ADMIN SISTEMI - PAROL TƏLƏB ET, SONRA TARİXCƏ
# ========================
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Əgər artıq daxil olubsa
    if admin_sessions.get(user_id):
        await show_admin_panel(update, context)
        return
    
    # Parol tələb et
    if not context.args:
        await update.message.reply_text(
            "🔐 Admin panelinə giriş\n\n"
            "İstifadə: /admin PAROL\n\nMəsələn: /admin sam3639mika"
        )
        return
    
    # Parolu yoxla
    password = context.args[0]
    
    if password == ADMIN_PASSWORD:
        admin_sessions[user_id] = True
        await show_admin_panel(update, context)
    else:
        await update.message.reply_text("❌ Yanlış parol! Giriş rədd edildi.")

async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panelini göstər - Bütün satış tarixcəsi"""
    
    # Bütün satışlar
    try:
        all_payments = db.collection("payments").order_by("date", direction=firestore.Query.DESCENDING).stream()
        payments_list = list(all_payments)
    except Exception as e:
        payments_list = []
        print(f"Satışları çəkmə xətası: {e}")
    
    # Promo kod ilə və without
    with_promo = [p for p in payments_list if p.to_dict().get("affiliateCode")]
    without_promo = [p for p in payments_list if not p.to_dict().get("affiliateCode")]
    
    # Affiliate məlumatları (bütün promo kodlar)
    try:
        affiliates = db.collection("affiliates").stream()
        affiliates_list = list(affiliates)
    except Exception as e:
        affiliates_list = []
        print(f"Affiliate çəkmə xətası: {e}")
    
    # Promo kod siyahısı (bütün kodlar)
    all_promo_codes = {}
    for aff_doc in affiliates_list:
        aff_data = aff_doc.to_dict()
        all_promo_codes[aff_data['promoCode']] = aff_data
    
    # HƏR PROMO KOD ÜÇÜN SATIŞ TARİXCƏSI (HƏTTA 0 OLSA BELƏ)
    text = "👑 *ADMIN PANEL - BÜTÜN SATIŞ TARİXCƏSI*\n\n"
    
    # 1. PROMO KODLA OLAN SATIŞLAR
    text += "🎫 *PROMO KODLA OLAN SATIŞLAR:*\n\n"
    
    if not all_promo_codes:
        text += "Heç bir promo kod yaradılmayıb.\n\n"
    else:
        for promo_code, aff_data in sorted(all_promo_codes.items()):
            name = aff_data.get('name', 'Naməlum')
            
            # Bu kodun satışları
            promo_payments = [p for p in payments_list if p.to_dict().get("affiliateCode") == promo_code]
            
            if not promo_payments:
                text += f"👤 {name} (`{promo_code}`)\n"
                text += f"   💵 Toplam: 0.00 AZN | Qazanc: 0.00 AZN\n"
                text += f"   📜 Satış sayı: 0\n\n"
            else:
                total = sum(p.to_dict().get('finalPrice', 0) for p in promo_payments)
                earned = total * 0.3
                
                text += f"👤 {name} (`{promo_code}`)\n"
                text += f"   💵 Toplam: {total:.2f} AZN | Qazanc: {earned:.2f} AZN\n"
                text += f"   📜 Satış sayı: {len(promo_payments)}\n"
                
                # Son 3 satışı göstər
                for idx, p_doc in enumerate(promo_payments[:3], 1):
                    p = p_doc.to_dict()
                    date = p.get("date", datetime.utcnow())
                    if isinstance(date, datetime):
                        date_str = date.strftime("%d.%m.%Y")
                    else:
                        date_str = str(date)[:10]
                    text += f"      {idx}. {date_str} | {p.get('email', '???')} | {p.get('finalPrice')} AZN\n"
                text += "\n"
    
    # 2. PROMO KODSUZ SATIŞLAR
    text += "❌ *PROMO KODSUZ SATIŞLAR:*\n\n"
    
    if not without_promo:
        text += "Promo kodsuz satış yoxdur.\n\n"
    else:
        total_without = sum(p.to_dict().get('finalPrice', 0) for p in without_promo)
        text += f"Ümumi məbləğ: {total_without:.2f} AZN\n"
        text += f"Satış sayı: {len(without_promo)}\n\n"
        
        for idx, p_doc in enumerate(without_promo[:10], 1):
            p = p_doc.to_dict()
            date = p.get("date", datetime.utcnow())
            if isinstance(date, datetime):
                date_str = date.strftime("%d.%m.%Y %H:%M")
            else:
                date_str = str(date)[:16]
            
            course = COURSES.get(p.get('course'), {}).get('name', p.get('course', '???'))
            text += f"{idx}. {date_str} | {p.get('email', '???')} | {p.get('finalPrice')} AZN | {course}\n"
        
        if len(without_promo) > 10:
            text += f"\n... və daha {len(without_promo) - 10} satış\n"
    
    # 3. ÜMUMI STATISTIKA
    total_revenue = sum(p.to_dict().get('finalPrice', 0) for p in payments_list)
    total_affiliate_payments = sum(p.to_dict().get('finalPrice', 0) for p in with_promo)
    total_commission = total_affiliate_payments * 0.3
    
    text += f"\n📊 *ÜMUMI STATISTIKA:*\n"
    text += f"• 💵 Ümumi gəlir: {total_revenue:.2f} AZN\n"
    text += f"• 🛒 Ümumi satış: {len(payments_list)}\n"
    text += f"• 🎫 Promo kodlu satış: {len(with_promo)} ({total_affiliate_payments:.2f} AZN)\n"
    text += f"• 🆓 Promo kodsuz satış: {len(without_promo)}\n"
    text += f"• 👥 Affiliate sayı: {len(affiliates_list)}\n"
    text += f"• 💸 Ümumi affiliate komissiyası: {total_commission:.2f} AZN"
    
    # Mesaj çox uzundursa, iki hissədə göndər
    if len(text) > 4000:
        part1 = text[:4000]
        await update.message.reply_text(part1, parse_mode="Markdown")
        await update.message.reply_text("...(davam edir)", parse_mode="Markdown")
    else:
        await update.message.reply_text(text, parse_mode="Markdown")

# ========================
# 🔹 START
# ========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data[user_id] = {"step": "course_selection"}

    keyboard = [[COURSES["frontend"]["name"]], [COURSES["ai"]["name"]]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(
        "🎓 *LuminaEdu* - Ödəniş Botu\n\n"
        "Hansı kurs üçün ödəniş etmək istəyirsiniz?",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

# ========================
# 🔹 MESAJ HANDLER
# ========================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id not in user_data:
        await update.message.reply_text("/start ilə başlayın")
        return

    step = user_data[user_id]["step"]

    # Kurs seçimi
    if step == "course_selection":
        for key, course in COURSES.items():
            if course["name"] == text:
                user_data[user_id]["course"] = key
                user_data[user_id]["step"] = "email"
                await update.message.reply_text(
                    f"✅ *{course['name']}* seçildi\n"
                    f"💵 Qiymət: {course['price']} AZN\n\n"
                    "📧 Emailinizi daxil edin:",
                    parse_mode="Markdown",
                    reply_markup=ReplyKeyboardRemove()
                )
                return
        await update.message.reply_text("❌ Düzgün kurs seçin.")

    # Email - botActivationData kolleksiyasında userEmail fieldində axtar
    elif step == "email":
        if re.match(r"^[^@]+@[^@]+\.[^@]+$", text):
            email = text.lower()

            # Email botActivationData-da userEmail fieldində axtar
            bot_data_ref = db.collection("botActivationData")
            query = bot_data_ref.where("userEmail", "==", email).limit(1).stream()
            
            firebase_user = None
            for doc in query:
                firebase_user = {"id": doc.id, "ref": doc.reference, "data": doc.to_dict()}
                break

            if not firebase_user:
                await update.message.reply_text(
                    "❌ Sistemdə belə email yoxdur!\n\n"
                    "Zəhmət olmasa, kurs üçün qeydiyyatdan keçdiyiniz emaili daxil edin."
                )
                return

            user_data[user_id]["email"] = email
            user_data[user_id]["firebase_user"] = firebase_user
            user_data[user_id]["step"] = "promo"

            await update.message.reply_text(
                "Promo kodunuz varsa daxil edin, yoxdursa 'xeyr' yazın:"
            )
        else:
            await update.message.reply_text("❌ Düzgün email daxil edin (nümunə: ad@email.com)")

    # Promo
    elif step == "promo":
        course_key = user_data[user_id]["course"]
        base_price = COURSES[course_key]["price"]

        if text.lower() in ["xeyr", "yox", "no", "0"]:
            final_price = base_price
            user_data[user_id]["affiliateCode"] = None
            discount_text = "Endirim tətbiq edilmədi"
        else:
            promo = text.upper()
            docs = db.collection("affiliates").where("promoCode", "==", promo).limit(1).stream()
            affiliate = None
            for d in docs:
                affiliate = d
                break

            if affiliate:
                final_price = round(base_price * 0.9, 2)
                user_data[user_id]["affiliateCode"] = promo
                discount_text = f"🎫 Promo kod '{promo}' tətbiq edildi (10% endirim)"
            else:
                final_price = base_price
                user_data[user_id]["affiliateCode"] = None
                discount_text = "⚠️ Promo kod tapılmadı, endirim tətbiq edilmədi"

        user_data[user_id]["final_price"] = final_price
        user_data[user_id]["step"] = "payment"

        await update.message.reply_text(
            f"📚 Kurs: {COURSES[course_key]['name']}\n"
            f"💵 Əsas qiymət: {base_price} AZN\n"
            f"{discount_text}\n"
            f"💰 Yekun qiymət: *{final_price} AZN*\n\n"
            f"💳 Kart məlumatları:\n"
            f"`4169 7388 1234 5678`\n"
            f"👤 Ad Soyad\n\n"
            f"Ödəniş edib çek/qəbzi şəkil olaraq göndərin.",
            parse_mode="Markdown"
        )

# ========================
# 🔹 AKTİVLƏŞDİRMƏ - CODE FIELDİNDƏN AL
# ========================
async def find_and_activate_code(user_id):
    data = user_data[user_id]
    firebase_user = data["firebase_user"]
    course_key = data["course"]
    course_db_name = COURSES[course_key]["db_name"]

    bot_ref = db.collection("botActivationData").document(firebase_user["id"])
    doc_snap = bot_ref.get()

    if not doc_snap.exists:
        return None, "no_bot_data"

    bot_data = doc_snap.to_dict()
    
    # Kurs məlumatlarının olub-olmamasını yoxla
    courses_data = bot_data.get("courses", {})
    if course_db_name not in courses_data:
        return None, "course_not_found"
    
    course_info = courses_data[course_db_name]
    
    # CODE fieldindən aktivləşdirmə kodunu al
    activation_code = course_info.get("code")
    if not activation_code:
        return None, "no_code_found"
    
    # Əgər artıq aktivdirsə
    if course_info.get("status") == "active":
        return activation_code, "already_active"

    # Statusu active et
    batch = db.batch()
    batch.update(bot_ref, {f"courses.{course_db_name}.status": "active"})
    batch.commit()

    return activation_code, None

# ========================
# 🔹 PHOTO - EMAIL + PROMO KOD YOXLANISI ƏLAVƏ EDILDI
# ========================
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in user_data or user_data[user_id].get("step") != "payment":
        await update.message.reply_text("Öncə /start edin və ödəniş prosesini başladın.")
        return

    processing_msg = await update.message.reply_text("⏳ Çek yoxlanılır...")

    file = None
    if update.message.photo:
        file = await update.message.photo[-1].get_file()
    elif update.message.document and update.message.document.mime_type.startswith("image/"):
        file = await update.message.document.get_file()

    if not file:
        await processing_msg.edit_text("❌ Zəhmət olmasa şəkil göndərin.")
        return

    try:
        file_path = f"temp_{user_id}.jpg"
        await file.download_to_drive(file_path)
        extracted_text = await read_image_with_easyocr(file_path)
        os.remove(file_path)
        
        print(f"OCR Nəticəsi: {extracted_text}")  # Debug üçün
        
    except Exception as e:
        await processing_msg.edit_text(f"❌ Şəkil oxuma xətası: {str(e)}")
        return

    # OCR yoxlaması - açar sözlər və məbləğ
    if not check_payment_keywords(extracted_text):
        await processing_msg.edit_text(
            "❌ Çek təsdiqlənmədi!\n\n"
            "Çekdə aşağıdakılardan ən azı biri olmalıdır:\n"
            "• 'ödəniş', 'uğurlu oldu', 'təsdiq' kimi sözlər\n"
            "• Məbləğ (AZN/manat/rəqəm)\n\n"
            "Zəhmət olmasa aydın şəkil göndərin."
        )
        return

    # EMAIL + PROMO KOD YOXLANISI (Suni alışın qarşısını almaq üçün)
    data = user_data[user_id]
    email = data["email"]
    promo_code = data.get("affiliateCode")
    
    if promo_code:
        # Bu email + promo kod kombinasiyası əvvəl istifadə edilibmi?
        already_used = await check_email_promo_usage(email, promo_code)
        if already_used:
            await processing_msg.edit_text(
                "❌ Bu email ilə bu promo kod artıq istifadə edilib!\n\n"
                "Hər email ilə hər promo kod yalnız bir dəfə istifadə edilə bilər."
            )
            del user_data[user_id]
            return

    # Aktivləşdirmə kodunu al
    activation_code, err = await find_and_activate_code(user_id)
    
    if err == "already_active":
        await processing_msg.edit_text(
            f"⚠️ Bu kurs üçün artıq aktivləşdirmə kodu mövcuddur:\n"
            f"🔑 Kodunuz: `{activation_code}`",
            parse_mode="Markdown"
        )
        del user_data[user_id]
        return
    elif err == "no_code_found":
        await processing_msg.edit_text("❌ Aktivləşdirmə kodu tapılmadı! Adminlə əlaqə saxlayın.")
        return
    elif err:
        await processing_msg.edit_text(f"❌ Aktivləşdirmə xətası: {err}")
        return

    # Ödəniş qeydi yarat
    payment_data = {
        "email": email,
        "course": data["course"],
        "finalPrice": data["final_price"],
        "affiliateCode": promo_code,
        "date": datetime.utcnow(),
        "status": "completed"
    }
    
    db.collection("payments").add(payment_data)

    # Affiliate qazancını yenilə (30%) - HƏR UĞURLU SATIŞDA
    if promo_code:
        docs = db.collection("affiliates").where("promoCode", "==", promo_code).limit(1).stream()
        for d in docs:
            aff_ref = d.reference
            aff_data = d.to_dict()
            commission = data["final_price"] * 0.3
            
            # Yeni dəyərləri hesabla
            new_earned = aff_data.get("earned", 0) + commission
            new_total_sales = aff_data.get("totalSales", 0) + data["final_price"]
            
            aff_ref.update({
                "earned": new_earned,
                "totalSales": new_total_sales,
                "lastSale": datetime.utcnow()
            })
            
            print(f"✅ Affiliate {promo_code} üçün {commission:.2f} AZN qazanc əlavə edildi. Yeni balans: {new_earned:.2f} AZN")

    # User data təmizlə
    del user_data[user_id]

    await processing_msg.edit_text(
        f"✅ Ödəniş uğurla təsdiqləndi!\n\n"
        f"🔑 Aktivləşdirmə kodunuz:\n"
        f"`{activation_code}`\n\n"
        f"Bu kodu platformada daxil edərək kursa daxil ola bilərsiniz.\n\n"
        f"Uğurlar arzulayırıq! 🎉",
        parse_mode="Markdown"
    )

# ========================
# 🔹 MAIN
# ========================
def main():
    request = HTTPXRequest(connection_pool_size=8)
    app = ApplicationBuilder().token(TOKEN).request(request).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("affilatelumina", affiliate_register))
    app.add_handler(CommandHandler("satis", show_sales))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bot işləyir...")
    app.run_polling()

if __name__ == "__main__":
    main()