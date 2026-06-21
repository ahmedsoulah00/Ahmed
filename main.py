import os
import subprocess
import zipfile
import time
from datetime import datetime, timedelta
import psutil
import sqlite3
import logging
import threading
import sys
import random
from flask import Flask
import telebot
from telebot import types  # تم إصلاح الاستدعاء الناقص للأزرار

# --- Flask Keep Alive (Render Compatibility) ---
app = Flask('')

@app.route('/')
def home(): 
    return "<h1>I'm Marco File Host - Running 24/7</h1>", 200

def run_flask(): 
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()

# --- Configuration ---
TOKEN = '8847026836:AAGstxciNm_OzoUZ5HStB65dZXyhN4A4Nyw'
OWNER_ID = 7119011124
ADMIN_ID = 7119011124
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_BOTS_DIR = os.path.join(BASE_DIR, 'upload_bots')
DATABASE_PATH = os.path.join(BASE_DIR, 'bot_data.db')

os.makedirs(UPLOAD_BOTS_DIR, exist_ok=True)
bot = telebot.TeleBot(TOKEN)

# قاموس لتتبع العمليات المشغلة (PIDs) لكل مستخدم
running_processes = {}

# --- Database Initialize ---
def init_db():
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (user_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 10, approved INTEGER DEFAULT 0, expiry TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS vip_codes (code TEXT PRIMARY KEY, days INTEGER)''')
    conn.commit()
    conn.close()

init_db()

# --- Helper Logic ---
def is_approved(user_id):
    if user_id == OWNER_ID: return True
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute("SELECT approved FROM users WHERE user_id = ?", (user_id,))
    res = c.fetchone()
    conn.close()
    return res and res[0] == 1

# --- Handlers ---
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    
    # منح 10 نقاط + 4 أيام تجريبية تلقائية عند أول دخول
    expiry_date = (datetime.now() + timedelta(days=4)).isoformat()
    c.execute("INSERT OR IGNORE INTO users (user_id, points, approved, expiry) VALUES (?, 10, 0, ?)", (user_id, expiry_date))
    conn.commit()
    conn.close()

    if not is_approved(user_id):
        bot.reply_to(message, "⚠️ أهلاً بك! طلبك قيد الانتظار لموافقة الإدارة.")
        bot.send_message(OWNER_ID, f"🔔 طلب انضمام جديد من: {message.from_user.first_name}\nID: `{user_id}`", parse_mode="Markdown")
    else:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("📤 رفع ملف", "📂 فحص الملفات", "🎟️ تفعيل كود VIP", "📊 معلوماتي")
        if user_id == OWNER_ID: 
            markup.add("👑 لوحة الأدمن")
        bot.reply_to(message, "✅ أهلاً بك في البوت! تم منحك 10 نقاط و 4 أيام تشغيل تجريبية.", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "📊 معلوماتي")
def my_info(message):
    user_id = message.from_user.id
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute("SELECT points, expiry FROM users WHERE user_id = ?", (user_id,))
    res = c.fetchone()
    conn.close()
    
    if res:
        points, expiry = res
        exp_date = datetime.fromisoformat(expiry).strftime('%Y-%m-%d %H:%M')
        bot.reply_to(message, f"👤 **بيانات حسابك:**\n\n💰 النقاط المتبقية: {points}\n⏳ تاريخ انتهاء الاشتراك: `{exp_date}`", parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "🎟️ تفعيل كود VIP")
def vip_code(message):
    msg = bot.reply_to(message, "أرسل كود الـ VIP المراد تفعيله:")
    bot.register_next_step_handler(msg, process_vip)

def process_vip(message):
    code = message.text
    user_id = message.from_user.id
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute("SELECT days FROM vip_codes WHERE code = ?", (code,))
    res = c.fetchone()
    if res:
        days = res[0]
        # تمديد الاشتراك الحالي أو البدء من الآن
        c.execute("SELECT expiry FROM users WHERE user_id = ?", (user_id,))
        current_exp = c.fetchone()
        
        base_date = datetime.now()
        if current_exp and datetime.fromisoformat(current_exp[0]) > datetime.now():
            base_date = datetime.fromisoformat(current_exp[0])
            
        new_expiry = (base_date + timedelta(days=days)).isoformat()
        c.execute("UPDATE users SET expiry = ?, approved = 1 WHERE user_id = ?", (new_expiry, user_id))
        c.execute("DELETE FROM vip_codes WHERE code = ?", (code,))
        conn.commit()
        bot.reply_to(message, f"✅ تم تفعيل اشتراك VIP لمدة {days} يوم بنجاح!")
    else:
        bot.reply_to(message, "❌ كود غير صالح أو مستخدم مسبقاً.")
    conn.close()

# --- Admin Panel ---
@bot.message_handler(func=lambda m: m.text == "👑 لوحة الأدمن" and m.from_user.id == OWNER_ID)
def admin(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ موافقة مستخدم", callback_data="adm_approve"))
    markup.add(types.InlineKeyboardButton("🎫 صنع كود VIP", callback_data="adm_gen"))
    bot.reply_to(message, "👑 لوحة تحكم الإدارة العليا:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("adm_"))
def admin_cb(call):
    if call.data == "adm_gen":
        code = f"VIP-{random.randint(10000,99999)}"
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO vip_codes VALUES (?, 4)", (code,))
        conn.commit()
        conn.close()
        bot.send_message(call.message.chat.id, f"🎫 تم توليد كود VIP جديد بنجاح:\n`{code}` (صالح لـ 4 أيام)", parse_mode="Markdown")
        bot.answer_callback_query(call.id)
    elif call.data == "adm_approve":
        msg = bot.send_message(call.message.chat.id, "أرسل ID المستخدم المراد الموافقة عليه وتفعيله:")
        bot.register_next_step_handler(msg, approve)
        bot.answer_callback_query(call.id)

def approve(m):
    try:
        target_id = int(m.text)
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute("UPDATE users SET approved = 1 WHERE user_id = ?", (target_id,))
        conn.commit()
        conn.close()
        bot.send_message(m.chat.id, f"✅ تم قبول العضو بـ ID: `{target_id}` بنجاح.", parse_mode="Markdown")
        bot.send_message(target_id, "🎉 تهانينا! تمت الموافقة على حسابك من قبل الإدارة، يمكنك الآن استخدام كافة الميزات.")
    except Exception as e:
        bot.send_message(m.chat.id, f"❌ حدث خطأ، تأكد من إدخال الآيدي أرقام فقط.")

# --- File Operations (رفع وفحص الملفات) ---
@bot.message_handler(func=lambda m: m.text == "📤 رفع ملف")
def upload_file_prompt(message):
    if not is_approved(message.from_user.id):
        return bot.reply_to(message, "❌ حسابك غير مفعل.")
    msg = bot.reply_to(message, "قم بإرسال ملف البوت الخاص بك بصيغة `.py` لتشغيله:")
    bot.register_next_step_handler(msg, save_user_script)

def save_user_script(message):
    if not message.document or not message.document.file_name.endswith('.py'):
        return bot.reply_to(message, "❌ خطأ! يرجى إرسال ملف ينتهي بامتداد `.py` فقط.")
    
    user_id = message.from_user.id
    user_dir = os.path.join(UPLOAD_BOTS_DIR, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    
    file_info = bot.get_file(message.document.file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    file_path = os.path.join(user_dir, "main.py")
    with open(file_path, 'wb') as new_file:
        new_file.write(downloaded_file)
        
    bot.reply_to(message, "📥 تم استقبال الملف بنجاح! جاري محاولة تشغيله بالخلفية...")
    
    # إنهاء أي عملية سابقة للمستخدم قبل تشغيل الملف الجديد
    stop_user_process(user_id)
    
    # تشغيل ملف المستخدم عبر Subprocess
    try:
        proc = subprocess.Popen([sys.executable, file_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        running_processes[user_id] = proc
        bot.send_message(user_id, "🟢 تم تشغيل البوت الخاص بك في الخلفية بنجاح!")
    except Exception as e:
        bot.send_message(user_id, f"❌ فشل تشغيل الملف. السبب: {str(e)}")

def stop_user_process(user_id):
    if user_id in running_processes:
        try:
            running_processes[user_id].terminate()
            running_processes[user_id].wait(timeout=2)
        except Exception:
            pass
        del running_processes[user_id]

@bot.message_handler(func=lambda m: m.text == "📂 فحص الملفات")
def check_files(message):
    user_id = message.from_user.id
    status = "🟢 مستقر ويعمل" if user_id in running_processes and running_processes[user_id].poll() is None else "🔴 متوقف"
    bot.reply_to(message, f"📊 **حالة ملفاتك البرمجية:**\n\n📁 الملف الأساسي: `main.py`\n⚡ الحالة الحالية: {status}", parse_mode="Markdown")

# --- Background Expiry Monitor ---
def monitor_expiry():
    while True:
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            c = conn.cursor()
            c.execute("SELECT user_id, expiry FROM users")
            rows = c.fetchall()
            conn.close()
            
            for u_id, exp in rows:
                if datetime.now() > datetime.fromisoformat(exp):
                    # إيقاف فوري لأي عملية للمستخدم منتهي الصلاحية
                    if u_id in running_processes:
                        stop_user_process(u_id)
                        try:
                            bot.send_message(u_id, "⚠️ انتهت فترة اشتراكك التجريبية (4 أيام)! يرجى تفعيل كود VIP للاستمرار.")
                        except Exception:
                            pass
        except Exception as e:
            pass
        time.sleep(60) # فحص كل دقيقة بدلاً من ساعة للتأكد من المزامنة الفورية

# --- Start System ---
if __name__ == "__main__":
    # تشغيل الـ Keep Alive لـ Render
    keep_alive()
    
    # تشغيل مراقب الصلاحية في الخلفية
    threading.Thread(target=monitor_expiry, daemon=True).start()
    
    print("🤖 Marco File Host Bot is completely running...")
    bot.infinity_polling()
