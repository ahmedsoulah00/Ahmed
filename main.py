import telebot
import subprocess
import os
import zipfile
import tempfile
import shutil
from telebot import types
import time
from datetime import datetime, timedelta
import psutil
import sqlite3
import json
import logging
import signal
import threading
import re
import sys
import atexit
import requests

# --- Flask Keep Alive ---
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "I'am Marco File Host"

def run_flask():
  port = int(os.environ.get("PORT", 8080))
  app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    print("Flask Keep-Alive server started.")
# --- End Flask Keep Alive ---

# --- Configuration (تم تحديث يوزر حسابك هنا بالظبط) ---
TOKEN = '8452234309:AAHRnslpCnrM2Rjnjj5F3WyyQH30mM-dHBc'
OWNER_ID = 7119011124
ADMIN_ID = 7119011124
YOUR_USERNAME = '@DDarkNetConfigs_1'
UPDATE_CHANNEL = 'https://t.me/AHMED_GCP'

# Folder setup - using absolute paths
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_BOTS_DIR = os.path.join(BASE_DIR, 'upload_bots')
PENDING_UPLOADS_DIR = os.path.join(BASE_DIR, 'pending_uploads') 
IROTECH_DIR = os.path.join(BASE_DIR, 'inf')
DATABASE_PATH = os.path.join(IROTECH_DIR, 'bot_data.db')

# File upload limits
FREE_USER_LIMIT = 3
SUBSCRIBED_USER_LIMIT = 15
ADMIN_LIMIT = 999
OWNER_LIMIT = float('inf')

# Points system configuration
UPLOAD_COST = 10 
DAILY_BONUS_POINTS = 5 

# File status constants
FILE_STATUS_PENDING = 'pending'
FILE_STATUS_APPROVED = 'approved'
FILE_STATUS_REJECTED = 'rejected'
FILE_STATUS_MALICIOUS = 'malicious' 

# Create necessary directories
os.makedirs(UPLOAD_BOTS_DIR, exist_ok=True)
os.makedirs(PENDING_UPLOADS_DIR, exist_ok=True) 
os.makedirs(IROTECH_DIR, exist_ok=True)

# Initialize bot
bot = telebot.TeleBot(TOKEN)

# --- Data structures ---
bot_scripts = {}
user_subscriptions = {}
user_files = {} 
active_users = set()
admin_ids = {ADMIN_ID, OWNER_ID}
banned_users_set = set() 
user_points = {} 
bot_locked = False

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Command Button Layouts (ReplyKeyboardMarkup) ---
COMMAND_BUTTONS_LAYOUT_USER_SPEC = [
    ["📢 قناة التحديثات"],
    ["📤 رفع ملف", "📂 فحص الملفات"],
    ["⚡ سرعة البوت", "📊 الإحصائيات"],
    ["📞 التواصل مع المالك"]
]
ADMIN_COMMAND_BUTTONS_LAYOUT_USER_SPEC = [
    ["📢 قناة التحديثات"],
    ["📤 رفع ملف", "📂 فحص الملفات"],
    ["⚡ سرعة البوت", "📊 الإحصائيات"],
    ["💳 الاشتراكات", "📢 بث رسالة"],
    ["🔒 قفل البوت", "🟢 تشغيل كل الأكواد"],
    ["👑 لوحة الأدمن", "📞 التواصل مع المالك"]
]

# --- Database Setup ---
def init_db():
    """Initialize the database with required tables"""
    logger.info(f"Initializing database at: {DATABASE_PATH}")
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS subscriptions
                     (user_id INTEGER PRIMARY KEY, expiry TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_files
                     (user_id INTEGER, file_name TEXT, file_type TEXT, status TEXT DEFAULT 'pending',
                      PRIMARY KEY (user_id, file_name))''')
        c.execute('''CREATE TABLE IF NOT EXISTS active_users
                     (user_id INTEGER PRIMARY KEY, last_interaction TEXT, points INTEGER DEFAULT 0)''') 
        c.execute('''CREATE TABLE IF NOT EXISTS admins
                     (user_id INTEGER PRIMARY KEY)''')
        c.execute('''CREATE TABLE IF NOT EXISTS banned_users
                     (user_id INTEGER PRIMARY KEY)''') 

        try: c.execute("ALTER TABLE user_files ADD COLUMN status TEXT DEFAULT 'pending'")
        except sqlite3.OperationalError: pass 

        try: c.execute("ALTER TABLE active_users ADD COLUMN points INTEGER DEFAULT 0")
        except sqlite3.OperationalError: pass 

        try: c.execute("ALTER TABLE active_users ADD COLUMN last_interaction TEXT")
        except sqlite3.OperationalError: pass 

        c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (OWNER_ID,))
        if ADMIN_ID != OWNER_ID:
             c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (ADMIN_ID,))
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"❌ Database initialization error: {e}", exc_info=True)

def load_data():
    """Load data from database into memory"""
    logger.info("Loading data from database...")
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()

        c.execute('SELECT user_id, expiry FROM subscriptions')
        for user_id, expiry in c.fetchall():
            try:
                user_subscriptions[user_id] = {'expiry': datetime.fromisoformat(expiry)}
            except ValueError:
                logger.warning(f"⚠️ Invalid expiry date format for user {user_id}: {expiry}. Skipping.")

        c.execute('SELECT user_id, file_name, file_type, status FROM user_files')
        for user_id, file_name, file_type, status in c.fetchall():
            if user_id not in user_files:
                user_files[user_id] = []
            user_files[user_id].append((file_name, file_type, status))

        c.execute('SELECT user_id, points FROM active_users')
        for user_id, points in c.fetchall():
            active_users.add(user_id)
            user_points[user_id] = points

        c.execute('SELECT user_id FROM admins')
        admin_ids.update(user_id for (user_id,) in c.fetchall())

        c.execute('SELECT user_id FROM banned_users')
        banned_users_set.update(user_id for (user_id,) in c.fetchall())

        conn.close()
        logger.info(f"Data loaded: {len(active_users)} users, {len(user_subscriptions)} subscriptions, {len(admin_ids)} admins, {len(banned_users_set)} banned users.")
    except Exception as e:
        logger.error(f"❌ Error loading data: {e}", exc_info=True)

init_db()
load_data()

# --- Helper Functions ---
def is_subscribed(user_id):
    """Check if user is subscribed to the required channel"""
    if user_id in admin_ids:
        return True
    
    # Extract channel username from link
    channel_username = UPDATE_CHANNEL.split('/')[-1]
    if not channel_username.startswith('@'):
        channel_username = '@' + channel_username

    try:
        member = bot.get_chat_member(channel_username, user_id)
        if member.status in ['member', 'administrator', 'creator']:
            return True
        return False
    except Exception as e:
        logger.error(f"Error checking subscription for user {user_id}: {e}")
        return True 

def check_subscription(func):
    """Decorator to enforce channel subscription"""
    def wrapper(message, *args, **kwargs):
        user_id = message.from_user.id
        if bot_locked and user_id not in admin_ids:
            bot.reply_to(message, "🔒 البوت مقفل حالياً للصيانة من قبل المالك.")
            return

        if user_id in banned_users_set:
            bot.reply_to(message, "❌ أنت محظور من استخدام هذا البوت.")
            return

        if not is_subscribed(user_id):
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("📢 اشترك في القناة", url=UPDATE_CHANNEL))
            bot.reply_to(message, f"⚠️ يجب عليك الاشتراك في قناة البوت أولاً لاستخدامه:\n{UPDATE_CHANNEL}\n\nبعد الاشتراك، أرسل /start مجدداً.", reply_markup=markup)
            return
        return func(message, *args, **kwargs)
    return wrapper

def get_user_buttons(user_id):
    """Get keyboard layout depending on user status"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    layout = ADMIN_COMMAND_BUTTONS_LAYOUT_USER_SPEC if user_id in admin_ids else COMMAND_BUTTONS_LAYOUT_USER_SPEC
    for row in layout:
        markup.add(*[types.KeyboardButton(text) for text in row])
    return markup

def get_user_limit(user_id):
    """Get the maximum number of files a user can run"""
    if user_id == OWNER_ID: return OWNER_LIMIT
    if user_id in admin_ids: return ADMIN_LIMIT
    if user_id in user_subscriptions:
        if datetime.now() < user_subscriptions[user_id]['expiry']:
            return SUBSCRIBED_USER_LIMIT
    return FREE_USER_LIMIT

def get_running_count(user_id):
    """Count currently running scripts for a user"""
    count = 0
    for key, proc in list(bot_scripts.items()):
        if str(key).startswith(f"{user_id}_"):
            if proc.poll() is None:  # Still running
                count += 1
            else:
                del bot_scripts[key] # Cleanup dead process reference
    return count

def kill_process_tree(pid):
    """Kill process and all its children"""
    try:
        if isinstance(pid, subprocess.Popen):
            p = psutil.Process(pid.pid)
        else:
            p = psutil.Process(int(pid))
        for child in p.children(recursive=True):
            child.kill()
        p.kill()
    except psutil.NoSuchProcess:
        pass
    except Exception as e:
        logger.error(f"Error killing process {pid}: {e}")

# --- Command Handlers ---
@bot.message_handler(commands=['start'])
@check_subscription
def send_welcome(message):
    user_id = message.from_user.id
    username = message.from_user.username or "No Username"
    first_name = message.from_user.first_name or "User"
    
    # Save user to DB
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('INSERT OR IGNORE INTO active_users (user_id, last_interaction, points) VALUES (?, ?, ?)', 
                  (user_id, datetime.now().isoformat(), 50)) # 50 welcome points
        c.execute('UPDATE active_users SET last_interaction = ? WHERE user_id = ?', 
                  (datetime.now().isoformat(), user_id))
        conn.commit()
        
        # Reload memory points
        c.execute('SELECT points FROM active_users WHERE user_id = ?', (user_id,))
        res = c.fetchone()
        if res: user_points[user_id] = res[0]
        
        conn.close()
    except Exception as e:
        logger.error(f"Error saving user start data: {e}")

    active_users.add(user_id)
    if user_id not in user_points: user_points[user_id] = 50

    welcome_text = (
        f"🙋‍♂️ أهلاً بك يا {first_name} في بوت استضافة ورفع الملفات!\n\n"
        f"🆔 معرفك: `{user_id}`\n"
        f"🪙 نقاطك الحالية: *{user_points.get(user_id, 50)}* نقطة\n"
        f"🚀 عدد الملفات المتاحة لك لتشغيلها معاً: `{get_running_count(user_id)}/{get_user_limit(user_id)}`\n\n"
        "استخدم الأزرار بالأسفل للتحكم وإدارة ملفاتك وسيرفراتك بكل سهولة."
    )
    if user_id in admin_ids:
        welcome_text += "\n\n👑 *أنت مسؤول (Admin) في هذا البوت. لديك كامل الصلاحيات لفتح لوحة التحكم.*"
        
    bot.send_message(user_id, welcome_text, parse_mode='Markdown', reply_markup=get_user_buttons(user_id))

# --- File Handling (Upload/Check) ---
@bot.message_handler(func=lambda m: m.text == "📤 رفع ملف")
@check_subscription
def upload_file_prompt(message):
    user_id = message.from_user.id
    
    if get_running_count(user_id) >= get_user_limit(user_id):
        bot.reply_to(message, f"⚠️ لقد وصلت للحد الأقصى المسموح لك من الملفات المشغلة في نفس الوقت (`{get_user_limit(user_id)}` ملف). يرجى إيقاف ملف قديم أولاً عبر قسم 'فحص الملفات'.")
        return

    current_points = user_points.get(user_id, 0)
    if current_points < UPLOAD_COST and user_id not in admin_ids:
        bot.reply_to(message, f"🪙 نقاطك غير كافية! تكلفة الرفع هي `{UPLOAD_COST}` نقاط، وأنت تملك `{current_points}` فقط. يمكنك طلب نقاط من المالك.")
        return

    msg = bot.send_message(user_id, "📁 يرجى إرسال ملف البوت البرمجي الآن كـ (Document).\n\n*الامتدادات المدعومة:* `.py` أو ملف مضغوط `.zip` يحتوي على مشروعك.", parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, process_file_upload)

def process_file_upload(message):
    user_id = message.from_user.id
    if not message.document:
        bot.send_message(user_id, "❌ لم تقم بإرسال مستند صالح. تم إلغاء العملية.", reply_markup=get_user_buttons(user_id))
        return

    file_info = bot.get_file(message.document.file_id)
    file_name = message.document.file_name
    ext = os.path.splitext(file_name)[1].lower()

    if ext not in ['.py', '.zip']:
        bot.send_message(user_id, "❌ امتداد الملف غير مدعوم! يجب إرسال ملف `.py` أو `.zip` فقط.", reply_markup=get_user_buttons(user_id))
        return

    bot.send_message(user_id, "⏳ جاري تحميل وفحص الملف الخاص بك...")

    try:
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Save to database and filesystem
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        
        is_malicious = False
        if ext == '.py':
            content = downloaded_file.decode('utf-8', errors='ignore')
            danger_words = ['rm -rf /', 'shutil.rmtree', 'os.system("rm']
            if any(word in content for word in danger_words):
                is_malicious = True

        status = FILE_STATUS_MALICIOUS if is_malicious else (FILE_STATUS_APPROVED if user_id in admin_ids else FILE_STATUS_PENDING)

        if is_malicious:
            bot.send_message(user_id, "🚨 تم رفض الملف تلقائياً! الملف يحتوي على أكواد قد تكون ضارة أو تدميرية للسيرفر.", reply_markup=get_user_buttons(user_id))
            conn.close()
            return

        if user_id not in admin_ids:
            user_points[user_id] = max(0, user_points.get(user_id, 0) - UPLOAD_COST)
            c.execute('UPDATE active_users SET points = ? WHERE user_id = ?', (user_points[user_id], user_id))

        c.execute('INSERT OR REPLACE INTO user_files (user_id, file_name, file_type, status) VALUES (?, ?, ?, ?)',
                  (user_id, file_name, ext, status))
        conn.commit()
        conn.close()

        if status == FILE_STATUS_APPROVED:
            target_path = os.path.join(UPLOAD_BOTS_DIR, f"{user_id}_{file_name}")
            with open(target_path, 'wb') as f:
                f.write(downloaded_file)
            
            start_user_script(user_id, file_name, target_path, ext)
        else:
            target_path = os.path.join(PENDING_UPLOADS_DIR, f"{user_id}_{file_name}")
            with open(target_path, 'wb') as f:
                f.write(downloaded_file)
                
            bot.send_message(user_id, "⏱️ تم رفع ملفك بنجاح! هو الآن في قائمة الانتظار، وسيتم مراجعته وتفعيله من قبل الإدارة قريباً جداً.", reply_markup=get_user_buttons(user_id))
            
            notify_text = f"📥 *ملف جديد في الانتظار!*\n\n👤 المستخدم: `{user_id}`\n📄 اسم الملف: `{file_name}`\n📦 النوع: `{ext}`\n\nقم بفتح لوحة الأدمن للموافقة عليه أو رفضه."
            bot.send_message(OWNER_ID, notify_text, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error handling uploaded file: {e}", exc_info=True)
        bot.send_message(user_id, "❌ حدث خطأ داخلي أثناء حفظ وتشغيل ملفك. يرجى المحاولة لاحقاً.", reply_markup=get_user_buttons(user_id))

def start_user_script(user_id, file_name, path, ext):
    """Launch user script in background and manage process logging"""
    key = f"{user_id}_{file_name}"
    
    if key in bot_scripts:
        kill_process_tree(bot_scripts[key])

    try:
        if ext == '.py':
            proc = subprocess.Popen([sys.executable, path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            bot_scripts[key] = proc
            bot.send_message(user_id, f"🟢 تم تفعيل وتشغيل ملفك بنجاح وعمل الاستضافة له برقم معرف عشوائي!\n📄 الملف: `{file_name}`", parse_mode='Markdown', reply_markup=get_user_buttons(user_id))
        elif ext == '.zip':
            extract_dir = os.path.join(UPLOAD_BOTS_DIR, f"extract_{user_id}_{os.path.splitext(file_name)[0]}")
            os.makedirs(extract_dir, exist_ok=True)
            
            with zipfile.ZipFile(path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
                
            main_file = None
            for f in os.listdir(extract_dir):
                if f in ['main.py', 'bot.py', 'index.py']:
                    main_file = os.path.join(extract_dir, f)
                    break
            if not main_file:
                for f in os.listdir(extract_dir):
                    if f.endswith('.py'):
                        main_file = os.path.join(extract_dir, f)
                        break
                        
            if main_file:
                proc = subprocess.Popen([sys.executable, main_file], cwd=extract_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                bot_scripts[key] = proc
                bot.send_message(user_id, f"🟢 تم فك الضغط وتشغيل المشروع المضغوط بنجاح!\n📄 الملف الأساسي المكتشف: `{os.path.basename(main_file)}`", parse_mode='Markdown', reply_markup=get_user_buttons(user_id))
            else:
                bot.send_message(user_id, "❌ فشل تشغيل الـ Zip! لم يتم العثور على أي ملف تشغيلي بامتداد `.py` داخل المجلد الرئيسي.", reply_markup=get_user_buttons(user_id))
    except Exception as e:
        logger.error(f"Failed to run user script {key}: {e}")
        bot.send_message(user_id, f"❌ حدث خطأ برمجي عند محاولة إقلاع ملفك في الخادم:\n`{e}`", parse_mode='Markdown', reply_markup=get_user_buttons(user_id))

@bot.message_handler(func=lambda m: m.text == "📂 فحص الملفات")
@check_subscription
def check_user_files(message):
    user_id = message.from_user.id
    
    if user_id not in user_files or not user_files[user_id]:
        bot.reply_to(message, "📂 ليس لديك أي ملفات مرفوعة أو مسجلة في السيرفر حتى الآن.")
        return

    text = "📂 *قائمة الملفات الخاصة بك وحالتها الآن:*\n\n"
    markup = types.InlineKeyboardMarkup()
    
    for idx, (f_name, f_type, status) in enumerate(user_files[user_id]):
        key = f"{user_id}_{f_name}"
        is_running = False
        if key in bot_scripts and bot_scripts[key].poll() is None:
            is_running = True
            
        status_emoji = "🟢 يعمل" if is_running else ("⏳ في الانتظار" if status == FILE_STATUS_PENDING else "🔴 متوقف/مرفوض")
        text += f"{idx+1}. `{f_name}` | الحالة: {status_emoji}\n"
        
        if is_running:
            markup.add(types.InlineKeyboardButton(f"🛑 إيقاف {f_name[:15]}", callback_data=f"stop_proc_{idx}"))
        elif status == FILE_STATUS_APPROVED:
            markup.add(types.InlineKeyboardButton(f"▶️ تشغيل {f_name[:15]}", callback_data=f"start_proc_{idx}"))
            
    bot.send_message(user_id, text, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith(('stop_proc_', 'start_proc_')))
def handle_proc_toggle(call):
    user_id = call.from_user.id
    action, idx_str = call.data.rsplit('_', 1)
    idx = int(idx_str)
    
    if user_id not in user_files or idx >= len(user_files[user_id]):
        bot.answer_callback_query(call.id, "❌ لم يتم العثور على بيانات الملف.")
        return
        
    f_name, f_type, status = user_files[user_id][idx]
    key = f"{user_id}_{f_name}"
    
    if action == 'stop_proc':
        if key in bot_scripts:
            kill_process_tree(bot_scripts[key])
            del bot_scripts[key]
            bot.answer_callback_query(call.id, "🛑 تم إيقاف الملف وقتل العملية بنجاح.")
        else:
            bot.answer_callback_query(call.id, "⚠️ الملف متوقف بالفعل.")
    elif action == 'start_proc':
        if get_running_count(user_id) >= get_user_limit(user_id):
            bot.answer_callback_query(call.id, "⚠️ لا يمكنك التشغيل، وصلت للحد الأقصى!")
            return
            
        target_path = os.path.join(UPLOAD_BOTS_DIR, f"{user_id}_{f_name}")
        if os.path.exists(target_path):
            start_user_script(user_id, f_name, target_path, f_type)
            bot.answer_callback_query(call.id, "▶️ جاري بدء تشغيل السكريبت...")
        else:
            bot.answer_callback_query(call.id, "❌ ملف السورس غير موجود في مسار العمل!")
            
    try: bot.delete_message(user_id, call.message.message_id)
    except: pass
    check_user_files(call.message)

# --- Standard Info Buttons ---
@bot.message_handler(func=lambda m: m.text == "📢 قناة التحديثات")
def info_channel(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔗 اضغط هنا لدخول القناة", url=UPDATE_CHANNEL))
    bot.reply_to(message, f"📢 تابع آخر الأخبار والتحديثات الرسمية الخاصة بنا عبر قناتنا الرسمية على تليجرام من هنا 👇", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "⚡ سرعة البوت")
def info_speed(message):
    start_time = time.time()
    msg = bot.reply_to(message, "⚡ جاري حساب سرعة الاستجابة وبنق السيرفر الحالي...")
    end_time = time.time()
    ping = round((end_time - start_time) * 1000, 2)
    
    cpu_usage = psutil.cpu_percent()
    ram_info = psutil.virtual_memory()
    
    status_text = (
        f"🚀 *سرعة استجابة البوت الحالية:* `{ping} ms`\n\n"
        f"📊 *استهلاك الخادم الإجمالي:*\n"
        f"🖥️ المعالج (CPU): `{cpu_usage}%`\n"
        f"💾 الذاكرة العشوائية (RAM): `{ram_info.percent}%`"
    )
    bot.edit_message_text(status_text, chat_id=msg.chat.id, message_id=msg.message_id, parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "📊 الإحصائيات")
@check_subscription
def info_stats(message):
    user_id = message.from_user.id
    total_running_all = sum(1 for p in bot_scripts.values() if p.poll() is None)
    
    stats_text = (
        "📊 *إحصائيات النظام العامة:*\n\n"
        f"👥 إجمالي المستخدمين النشطين: `{len(active_users)}`\n"
        f"🟢 إجمالي السكريبتات المشغلة الآن في الخادم: `{total_running_all}`\n"
        f"🛡️ عدد الأدمن والمشرفين: `{len(admin_ids)}`\n"
        f"⛔ المستخدمين في الحظر: `{len(banned_users_set)}`\n\n"
        f"📌 *إحصائياتك أنت:* \n"
        f"🪙 رصيد نقاطك: `{user_points.get(user_id, 0)}` نقطة.\n"
        f"📂 ملفاتك المشغلة حالياً: `{get_running_count(user_id)}/{get_user_limit(user_id)}`"
    )
    bot.reply_to(message, stats_text, parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "📞 التواصل مع المالك")
def contact_owner(message):
    bot.reply_to(message, f"📞 لمواجهة أي مشاكل أو لطلب شراء نقاط واشتراكات مدفوعة، يرجى التواصل مباشرة مع المالك عبر المعرف التالي:\n\n{YOUR_USERNAME}")

# --- Admin Control Panel Features ---
@bot.message_handler(func=lambda m: m.text == "👑 لوحة الأدمن" and m.from_user.id in admin_ids)
def admin_panel(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📥 إدارة طلبات الرفع والانتظار", callback_data="adm_manage_pending"))
    markup.add(types.InlineKeyboardButton("🪙 منح / سحب نقاط", callback_data="adm_modify_points"),
               types.InlineKeyboardButton("🚫 حظر / إلغاء حظر", callback_data="adm_toggle_ban"))
    markup.add(types.InlineKeyboardButton("➕ إضافة أدمن جديد", callback_data="adm_add_admin"))
    bot.reply_to(message, "👑 *أهلاً بك في لوحة تحكم المسؤولين.*\nيرجى اختيار أحد الإجراءات الإدارية التالية للتحكم بالسيرفر:", parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('adm_'))
def handle_admin_callbacks(call):
    user_id = call.from_user.id
    if user_id not in admin_ids:
        bot.answer_callback_query(call.id, "❌ عذراً، هذه اللوحة مخصصة للمشرفين فقط.")
        return
        
    action = call.data
    
    if action == 'adm_manage_pending':
        pending_list = []
        for u_id, files in user_files.items():
            for idx, (f_name, f_type, status) in enumerate(files):
                if status == FILE_STATUS_PENDING:
                    pending_list.append((u_id, f_name, f_type, idx))
                    
        if not pending_list:
            bot.answer_callback_query(call.id, "👌 لا توجد أي ملفات في قائمة الانتظار حالياً.")
            return
            
        u_id, f_name, f_type, orig_idx = pending_list[0]
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ موافقة وتشغيل", callback_data=f"aprv_{u_id}_{orig_idx}"),
                   types.InlineKeyboardButton("❌ رفض وحذف", callback_data=f"rjct_{u_id}_{orig_idx}"))
        
        bot.send_message(user_id, f"📥 *طلب معلق للمراجعة:*\n\n👤 حساب المستخدم: `{u_id}`\n📄 اسم الملف: `{f_name}`\n📦 النوع: `{f_type}`", parse_mode='Markdown', reply_markup=markup)
        bot.answer_callback_query(call.id)
        
    elif action == 'adm_modify_points':
        msg = bot.send_message(user_id, "🔢 أرسل معرف المستخدم (ID) ثم مسافة ثم عدد النقاط (بالموجب للإضافة وبالسالب للسحب).\nمثال: `7119011124 100`", parse_mode='Markdown')
        bot.register_next_step_handler(msg, process_admin_modify_points)
        bot.answer_callback_query(call.id)
        
    elif action == 'adm_toggle_ban':
        msg = bot.send_message(user_id, "🚫 أرسل معرف المستخدم (ID) لحظره أو إلغاء حظره فوراً من النظام.")
        bot.register_next_step_handler(msg, process_admin_toggle_ban)
        bot.answer_callback_query(call.id)

    elif action == 'adm_add_admin':
        if user_id != OWNER_ID:
            bot.answer_callback_query(call.id, "❌ هذا الخيار متاح للمالك الأساسي فقط وليس للأدمن.")
            return
        msg = bot.send_message(user_id, "➕ أرسل معرف المستخدم (ID) لترقيته إلى رتبة أدمن في البوت.")
        bot.register_next_step_handler(msg, process_admin_add_new)
        bot.answer_callback_query(call.id)

# --- Admin Step Handlers ---
def process_admin_modify_points(message):
    user_id = message.from_user.id
    try:
        parts = message.text.split()
        target_id = int(parts[0])
        amount = int(parts[1])
        
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('INSERT OR IGNORE INTO active_users (user_id, points) VALUES (?, 0)', (target_id,))
        c.execute('UPDATE active_users SET points = points + ? WHERE user_id = ?', (amount, target_id))
        conn.commit()
        
        c.execute('SELECT points FROM active_users WHERE user_id = ?', (target_id,))
        new_pts = c.fetchone()[0]
        user_points[target_id] = new_pts
        conn.close()
        
        bot.send_message(user_id, f"✅ تم تحديث النقاط بنجاح للمستخدم `{target_id}`. الرصيد الحالي له الآن: `{new_pts}` نقطة.", parse_mode='Markdown', reply_markup=get_user_buttons(user_id))
        bot.send_message(target_id, f"🪙 أهلاً بك، تم تعديل رصيد نقاطك من قبل الإدارة بمقدار `{amount}`. رصيدك الحالي هو: `{new_pts}` نقطة.")
    except Exception as e:
        bot.send_message(user_id, f"❌ حدث خطأ في الصياغة أو البيانات المدخلة: {e}", reply_markup=get_user_buttons(user_id))

def process_admin_toggle_ban(message):
    user_id = message.from_user.id
    try:
        target_id = int(message.text.strip())
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        
        if target_id in banned_users_set:
            banned_users_set.remove(target_id)
            c.execute('DELETE FROM banned_users WHERE user_id = ?', (target_id,))
            msg_text = f"🟢 تم إلغاء حظر المستخدم `{target_id}` بنجاح وإعادته للنظام."
        else:
            banned_users_set.add(target_id)
            c.execute('INSERT OR IGNORE INTO banned_users (user_id) VALUES (?)', (target_id,))
            msg_text = f"🚫 تم حظر المستخدم `{target_id}` بنجاح من كافة الصلاحيات."
            
        conn.commit()
        conn.close()
        bot.send_message(user_id, msg_text, parse_mode='Markdown', reply_markup=get_user_buttons(user_id))
    except Exception as e:
        bot.send_message(user_id, f"❌ يرجى إدخال ID أرقام صحيح فقط: {e}", reply_markup=get_user_buttons(user_id))

def process_admin_add_new(message):
    user_id = message.from_user.id
    try:
        target_id = int(message.text.strip())
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (target_id,))
        conn.commit()
        conn.close()
        
        admin_ids.add(target_id)
        bot.send_message(user_id, f"👑 تم ترقية وتعيين `{target_id}` كمسؤول أدمن إضافي في النظام.", parse_mode='Markdown', reply_markup=get_user_buttons(user_id))
        bot.send_message(target_id, "👑 مبروك! تم ترقيتك لمنصب مسؤول وأدمن في البوت من قبل المالك. أرسل /start لفتح لوحتك الجديدة.")
    except Exception as e:
        bot.send_message(user_id, f"❌ خطأ في المعرف: {e}", reply_markup=get_user_buttons(user_id))

@bot.callback_query_handler(func=lambda call: call.data.startswith(('aprv_', 'rjct_')))
def handle_file_moderation(call):
    user_id = call.from_user.id
    if user_id not in admin_ids: return
    
    action, target_id_str, idx_str = call.data.split('_')
    target_id = int(target_id_str)
    idx = int(idx_str)
    
    if target_id not in user_files or idx >= len(user_files[target_id]):
        bot.answer_callback_query(call.id, "❌ خطأ في تتبع بيانات الملف المعلق.")
        return
        
    f_name, f_type, _ = user_files[target_id][idx]
    pending_path = os.path.join(PENDING_UPLOADS_DIR, f"{target_id}_{f_name}")
    approved_path = os.path.join(UPLOAD_BOTS_DIR, f"{target_id}_{f_name}")
    
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    
    if action == 'aprv':
        if os.path.exists(pending_path):
            shutil.move(pending_path, approved_path)
            
        user_files[target_id][idx] = (f_name, f_type, FILE_STATUS_APPROVED)
        c.execute('UPDATE user_files SET status = ? WHERE user_id = ? AND file_name = ?', (FILE_STATUS_APPROVED, target_id, f_name))
        bot.send_message(target_id, f"✅ تمت الموافقة على ملفك `{f_name}` من قبل المشرفين، وجاري تشغيله واستضافته الآن تلقائياً!")
        start_user_script(target_id, f_name, approved_path, f_type)
        bot.answer_callback_query(call.id, "✅ تمت الموافقة والتشغيل بنجاح.")
    else:
        if os.path.exists(pending_path): os.remove(pending_path)
        user_files[target_id].pop(idx)
        c.execute('DELETE FROM user_files WHERE user_id = ? AND file_name = ?', (target_id, f_name))
        bot.send_message(target_id, f"❌ عذراً، تم رفض وحذف ملفك المرفوع `{f_name}` من قبل إدارة السيرفر بعد مراجعته.")
        bot.answer_callback_query(call.id, "❌ تم رفض الطلب وحذفه نهائياً.")
        
    conn.commit()
    conn.close()
    try: bot.delete_message(user_id, call.message.message_id)
    except: pass

@bot.message_handler(func=lambda m: m.text == "🔒 قفل البوت" and m.from_user.id in admin_ids)
def toggle_bot_lock(message):
    global bot_locked
    bot_locked = not bot_locked
    status_str = "🔒 مقفل الآن على عامة المستخدمين وللصيانة" if bot_locked else "🟢 مفتوح ومتاح للجميع الآن"
    bot.reply_to(message, f"⚙️ تم تغيير حالة البوت! البوت هو: *{status_str}*.", parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "🟢 تشغيل كل الأكواد" and m.from_user.id in admin_ids)
def start_all_approved_scripts(message):
    bot.reply_to(message, "⏳ جاري فحص ومحاولة تشغيل كافة السكريبتات المعتمدة والموجودة في مجلد الحفظ...")
    count = 0
    for u_id, files in user_files.items():
        for f_name, f_type, status in files:
            if status == FILE_STATUS_APPROVED:
                key = f"{u_id}_{f_name}"
                if key not in bot_scripts or bot_scripts[key].poll() is not None:
                    target_path = os.path.join(UPLOAD_BOTS_DIR, key)
                    if os.path.exists(target_path):
                        threading.Thread(target=start_user_script, args=(u_id, f_name, target_path, f_type), daemon=True).start()
                        count += 1
    bot.send_message(message.chat.id, f"✅ اكتمل الإجراء الإداري! تم إعادة تشغيل إقلاع لـ `{count}` ملف متوقف في الخادم بنجاح.", parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "📢 بث رسالة" and m.from_user.id in admin_ids)
def prompt_broadcast(message):
    msg = bot.reply_to(message, "📢 أرسل نص الرسالة التي تريد بثها وإرسالها لكل مستخدمي البوت المسجلين الآن:")
    bot.register_next_step_handler(msg, process_broadcast_send)

def process_broadcast_send(message):
    user_id = message.from_user.id
    text_to_send = message.text
    if not text_to_send:
        bot.send_message(user_id, "❌ رسالة فارغة، تم إلغاء البث.", reply_markup=get_user_buttons(user_id))
        return
        
    bot.send_message(user_id, f"⏳ جاري بدء الإرسال والبث إلى لـ `{len(active_users)}` مستخدم...")
    success, failure = 0, 0
    for u_id in list(active_users):
        try:
            bot.send_message(u_id, f"📢 *إشعار وبث عام من إدارة البوت:*\n\n{text_to_send}", parse_mode='Markdown')
            success += 1
            time.sleep(0.05)
        except Exception:
            failure += 1
            
    bot.send_message(user_id, f"📊 *اكتملت عملية البث بنجاح:*\n\n✅ تم التسليم لـ: `{success}` مستخدم\n❌ فشل الإرسال لـ: `{failure}` مستخدم (قاموا بحظر البوت غالباً).", parse_mode='Markdown', reply_markup=get_user_buttons(user_id))

@bot.message_handler(func=lambda m: m.text == "💳 الاشتراكات" and m.from_user.id in admin_ids)
def prompt_subscription_add(message):
    msg = bot.reply_to(message, "💳 لمنح اشتراك VIP بريميوم لمستخدم، يرجى إرسال الـ ID الخاص به ثم عدد الأيام الممنوحة له يفصل بينهما مسافة.\nمثال: `7119011124 30`")
    bot.register_next_step_handler(msg, process_add_subscription_days)

def process_add_subscription_days(message):
    user_id = message.from_user.id
    try:
        parts = message.text.split()
        target_id = int(parts[0])
        days = int(parts[1])
        
        expiry_date = datetime.now() + timedelta(days=days)
        user_subscriptions[target_id] = {'expiry': expiry_date}
        
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO subscriptions (user_id, expiry) VALUES (?, ?)', (target_id, expiry_date.isoformat()))
        conn.commit()
        conn.close()
        
        bot.send_message(user_id, f"✅ تم تفعيل الاشتراك المدفوع للمستخدم `{target_id}` ليكون صالحاً حتى `{expiry_date.strftime('%Y-%m-%d %H:%M')}`.", parse_mode='Markdown', reply_markup=get_user_buttons(user_id))
        bot.send_message(target_id, f"💳 تهانينا! منحتك الإدارة اشتراكاً مميزاً (VIP البريميوم) لتوسيع حدود ملفات الاستضافة الخاصة بك لمدة `{days}` أيام إضافية!")
    except Exception as e:
        bot.send_message(user_id, f"❌ خطأ بالبيانات، يرجى إدخال ID ثم مسافة ثم الأيام أرقام فقط: {e}", reply_markup=get_user_buttons(user_id))

# --- Daily Bonus Scheduler System ---
def start_daily_bonus_scheduler():
    def run_scheduler():
        while True:
            try:
                now = datetime.now()
                tomorrow = now + timedelta(days=1)
                midnight = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0, 0)
                seconds_to_wait = (midnight - now).total_seconds()
                time.sleep(max(seconds_to_wait, 10))
                
                conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
                c = conn.cursor()
                for u_id in list(active_users):
                    user_points[u_id] = user_points.get(u_id, 0) + DAILY_BONUS_POINTS
                    c.execute('UPDATE active_users SET points = ? WHERE user_id = ?', (user_points[u_id], u_id))
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error(f"Error in daily bonus scheduler loop: {e}")
                time.sleep(60)

    t = threading.Thread(target=run_scheduler, daemon=True)
    t.start()

# --- Shutdown Cleanup Handler ---
def cleanup():
    script_keys_to_stop = list(bot_scripts.keys())
    for key in script_keys_to_stop:
        if key in bot_scripts: kill_process_tree(bot_scripts[key])
    logger.warning("Cleanup finished.")
atexit.register(cleanup)

# --- Main Execution ---
if __name__ == '__main__':
    logger.info("="*40 + "\n🤖 Bot Starting Up...\n" + f"🐍 Python: {sys.version.split()[0]}\n" +
                f"🔧 Base Dir: {BASE_DIR}\n📁 Upload Dir: {UPLOAD_BOTS_DIR}\n" +
                f"📁 Pending Dir: {PENDING_UPLOADS_DIR}\n" +
                f"📊 Data Dir: {IROTECH_DIR}\n🔑 Owner ID: {OWNER_ID}\n🛡️ Admins: {admin_ids}\n" + "="*40)
    keep_alive()
    start_daily_bonus_scheduler()
    logger.info("🚀 Starting polling...")
    while True:
        try:
            bot.infinity_polling(logger_level=logging.INFO, timeout=60, long_polling_timeout=30)
        except requests.exceptions.ReadTimeout: time.sleep(5)
        except requests.exceptions.ConnectionError: time.sleep(15)
        except Exception as e:
            time.sleep(10)
