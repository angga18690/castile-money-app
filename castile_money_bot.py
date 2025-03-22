from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
import logging
import os
from dotenv import load_dotenv

# Konfigurasi logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load variabel lingkungan (jika menggunakan .env)
try:
    load_dotenv()
    BOT_TOKEN = os.getenv("BOT_TOKEN", "BOT_TOKEN=your_bot_token_here")
    MONETAG_URL = os.getenv("MONETAG_URL", "MONETAG_URL=your_monetag_url_here")
    ADMIN_IDS = [int(id) for id in os.getenv("ADMIN_IDS", "admin_ids=your_admin_id_here").split(",") if id]
except:
    # Fallback jika dotenv tidak tersedia
    BOT_TOKEN = "BOT_TOKEN", "BOT_TOKEN=your_bot_token_here"
    MONETAG_URL = "MONETAG_URL=your_monetag_url_here"
    ADMIN_IDS = ["admin_ids=your_admin_id_here"]  # ID admin Anda

# Inisialisasi database
def init_db():
    conn = sqlite3.connect('castile_money.db')
    cursor = conn.cursor()
    
    # Tabel pengguna
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        balance INTEGER DEFAULT 0,
        referral_code TEXT,
        referred_by INTEGER,
        join_date TEXT,
        last_active TEXT
    )
    ''')
    
    # Tabel transaksi
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        type TEXT,
        status TEXT,
        details TEXT,
        timestamp TEXT,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')
    
    conn.commit()
    conn.close()

# Fungsi untuk mendapatkan atau membuat pengguna
def get_or_create_user(user_id, username):
    conn = sqlite3.connect('castile_money.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        referral_code = f"REF{user_id}"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute(
            "INSERT INTO users (user_id, username, referral_code, join_date, last_active) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, referral_code, now, now)
        )
        conn.commit()
        
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
    else:
        # Update last_active
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("UPDATE users SET last_active = ? WHERE user_id = ?", (now, user_id))
        conn.commit()
    
    conn.close()
    return user

# Decorator untuk membatasi akses admin
def admin_only(func):
    @wraps(func)
    async def wrapped(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in ADMIN_IDS:
            await update.message.reply_text("⛔ Anda tidak memiliki izin untuk mengakses perintah ini.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

# Rate limiting untuk mencegah spam
last_command_time = {}
def rate_limit(seconds=60):
    def decorator(func):
        @wraps(func)
        async def wrapped(update, context, *args, **kwargs):
            user_id = update.effective_user.id
            current_time = datetime.now()
            
            if user_id in last_command_time:
                time_diff = (current_time - last_command_time[user_id]).total_seconds()
                
                if time_diff < seconds:
                    remaining = int(seconds - time_diff)
                    await update.message.reply_text(
                        f"⏳ Mohon tunggu {remaining} detik sebelum menggunakan perintah ini lagi."
                    )
                    return
            
            last_command_time[user_id] = current_time
            return await func(update, context, *args, **kwargs)
        return wrapped
    return decorator

# Fungsi untuk mendapatkan ID pengguna
async def get_my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    first_name = update.effective_user.first_name
    last_name = update.effective_user.last_name or ""
    language = update.effective_user.language_code
    
    message = (
        f"🆔 *Informasi ID Anda*\n\n"
        f"User ID: `{user_id}`\n"
        f"Username: @{username}\n"
        f"First: {first_name}\n"
        f"Last: {last_name}\n"
        f"Lang: {language}\n\n"
        f"Status Admin: {'✅ Ya' if user_id in ADMIN_IDS else '❌ Tidak'}"
    )
    
    await update.message.reply_text(message, parse_mode='Markdown')

# Fungsi untuk memulai bot
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    # Cek apakah ada parameter referral
    if context.args and context.args[0].startswith("REF"):
        referrer_code = context.args[0]
        # Proses referral (simpan ke database)
        conn = sqlite3.connect('castile_money.db')
        cursor = conn.cursor()
        
        # Dapatkan ID referrer
        cursor.execute("SELECT user_id FROM users WHERE referral_code = ?", (referrer_code,))
        referrer = cursor.fetchone()
        
        if referrer and referrer[0] != user_id:
            # Update user dengan referrer
            cursor.execute("UPDATE users SET referred_by = ? WHERE user_id = ? AND referred_by IS NULL", 
                          (referrer[0], user_id))
            
            # Tambahkan bonus ke referrer
            cursor.execute("UPDATE users SET balance = balance + 1000 WHERE user_id = ?", (referrer[0],))
            
            # Catat transaksi
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                "INSERT INTO transactions (user_id, amount, type, status, details, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                (referrer[0], 1000, "referral", "completed", f"Referral bonus from {user_id}", now)
            )
            
            conn.commit()
        
        conn.close()
    
    # Dapatkan atau buat user di database
    user = get_or_create_user(user_id, username)
    
    # Membuat tombol dengan Monetag URL
    keyboard = [
        [InlineKeyboardButton("Mulai Menghasilkan Sekarang", web_app=WebAppInfo(url=MONETAG_URL))],
        [InlineKeyboardButton("Cek Saldo", callback_data='check_balance')],
        [InlineKeyboardButton("Bukti Pembayaran", callback_data='payment_proof')],
        [InlineKeyboardButton("Referral", callback_data='referral')],
        [InlineKeyboardButton("Informasi Bot", callback_data='bot_info')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Pesan untuk pengguna
    message = (
        "🤖 *Castile Money Bot - Bot Penghasil Saldo E-Wallet*\n"
        "💰 *Dapatkan saldo DANA dengan mudah:*\n"
        "• Hanya dengan menonton iklan 15 detik\n"
        "• Minimal withdraw Rp 5.000\n"
        "• Pembayaran instan ke e-wallet\n\n"
        "✨ *Fitur Utama:*\n"
        "• Tonton iklan dapat saldo\n"
        "• Withdraw ke DANA\n"
        "• Cek saldo realtime\n"
        "• Sistem otomatis 24 jam\n\n"
        "🌟 _Start sekarang dan mulai menghasilkan!_\n"
    )
    
    # Kirim pesan ke pengguna dengan tombol
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

# Fungsi untuk referral
async def referral_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    # Ambil kode referral dari database
    conn = sqlite3.connect('castile_money.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT referral_code FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    referral_code = result[0] if result else f"REF{user_id}"
    referral_link = f"https://t.me/CastileMoney_Bot?start={referral_code}"
    
    message = (
        f"🔗 *Program Referral Castile Money*\n\n"
        f"Dapatkan bonus Rp1.000 untuk setiap teman yang bergabung!\n\n"
        f"Kode Referral Anda: `{referral_code}`\n"
        f"Link Referral Anda: {referral_link}\n\n"
        f"Bagikan link ini kepada teman Anda dan dapatkan bonus!"
    )
    
    await update.message.reply_text(message, parse_mode='Markdown')

# Fungsi untuk cek saldo
async def check_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Ambil saldo dari database
    conn = sqlite3.connect('castile_money.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    balance = result[0] if result else 0
    
    message = (
        f"💰 *Saldo Anda*\n\n"
        f"Saldo saat ini: Rp{balance:,}\n"
        f"Minimal penarikan: Rp5.000\n\n"
        f"Tonton lebih banyak iklan untuk menambah saldo!"
    )
    
    keyboard = [
        [InlineKeyboardButton("Tonton Iklan", web_app=WebAppInfo(url=MONETAG_URL))],
        [InlineKeyboardButton("Tarik Saldo", callback_data='withdraw')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

# Fungsi untuk menangani tombol callback
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if query.data == 'payment_proof':
        # Ambil bukti pembayaran dari database
        conn = sqlite3.connect('castile_money.db')
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT u.username, t.amount, t.timestamp 
            FROM transactions t 
            JOIN users u ON t.user_id = u.user_id 
            WHERE t.type = 'withdraw' AND t.status = 'completed' 
            ORDER BY t.timestamp DESC LIMIT 10
        """)
        
        payments = cursor.fetchall()
        conn.close()
        
        if not payments:
            message = "Belum ada bukti pembayaran saat ini."
        else:
            message = "📊 *Bukti Pembayaran Terbaru*\n\n"
            for i, (username, amount, timestamp) in enumerate(payments, 1):
                # Sembunyikan sebagian username untuk privasi
                if username and len(username) > 3:
                    masked_username = username[:2] + "*" * (len(username) - 3) + username[-1]
                else:
                    masked_username = "User"
                
                message += f"{i}. {masked_username}: Rp{amount:,} - {timestamp}\n"
        
        await query.edit_message_text(text=message, parse_mode='Markdown')
    
    elif query.data == 'bot_info':
        message = (
            "ℹ️ *Informasi Bot*\n\n"
            "Nama: CastileMoney_Bot\n"
            "Versi: 1.0.0\n"
            "Deskripsi: Bot penghasil saldo e-wallet dengan menonton iklan\n\n"
            "Cara Kerja:\n"
            "1. Tonton iklan 15 detik\n"
            "2. Dapatkan Rp100-500 per iklan\n"
            "3. Kumpulkan minimal Rp5.000\n"
            "4. Tarik ke DANA\n\n"
            "Hubungi admin: @aeiwa18"
        )
        
        await query.edit_message_text(text=message, parse_mode='Markdown')
    
    elif query.data == 'check_balance':
        # Ambil saldo dari database
        conn = sqlite3.connect('castile_money.db')
        cursor = conn.cursor()
        
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        
        balance = result[0] if result else 0
        
        message = (
            f"💰 *Saldo Anda*\n\n"
            f"Saldo saat ini: Rp{balance:,}\n"
            f"Minimal penarikan: Rp5.000\n\n"
            f"Tonton lebih banyak iklan untuk menambah saldo!"
        )
        
        keyboard = [
            [InlineKeyboardButton("Tonton Iklan", web_app=WebAppInfo(url=MONETAG_URL))],
            [InlineKeyboardButton("Tarik Saldo", callback_data='withdraw')],
            [InlineKeyboardButton("Kembali", callback_data='back_to_main')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text=message, reply_markup=reply_markup, parse_mode='Markdown')
    
    elif query.data == 'withdraw':
        # Ambil saldo dari database
        conn = sqlite3.connect('castile_money.db')
        cursor = conn.cursor()
        
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        
        balance = result[0] if result else 0
        
        if balance < 5000:
            await query.edit_message_text(
                text="❌ Saldo Anda belum mencukupi untuk penarikan.\nMinimal penarikan adalah Rp5.000."
            )
            return
        
        # Meminta nomor DANA
        message = (
            "💳 *Penarikan Saldo*\n\n"
            f"Saldo Anda: Rp{balance:,}\n"
            "Silakan kirimkan nomor DANA Anda dengan format:\n"
            "`/dana 08xxxxxxxxxx`"
        )
        
        await query.edit_message_text(text=message, parse_mode='Markdown')
    
    elif query.data == 'referral':
        # Ambil kode referral dari database
        conn = sqlite3.connect('castile_money.db')
        cursor = conn.cursor()
        
        cursor.execute("SELECT referral_code FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        
        referral_code = result[0] if result else f"REF{user_id}"
        referral_link = f"https://t.me/CastileMoney_Bot?start={referral_code}"
        
        message = (
            f"🔗 *Program Referral Castile Money*\n\n"
            f"Dapatkan bonus Rp1.000 untuk setiap teman yang bergabung!\n\n"
            f"Kode Referral Anda: `{referral_code}`\n"
            f"Link Referral Anda: {referral_link}\n\n"
            f"Bagikan link ini kepada teman Anda dan dapatkan bonus!"
        )
        
        keyboard = [
            [InlineKeyboardButton("Kembali", callback_data='back_to_main')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text=message, reply_markup=reply_markup, parse_mode='Markdown')
    
    elif query.data == 'back_to_main':
        # Kembali ke menu utama
        keyboard = [
            [InlineKeyboardButton("Mulai Menghasilkan Sekarang", web_app=WebAppInfo(url=MONETAG_URL))],
            [InlineKeyboardButton("Cek Saldo", callback_data='check_balance')],
            [InlineKeyboardButton("Bukti Pembayaran", callback_data='payment_proof')],
            [InlineKeyboardButton("Referral", callback_data='referral')],
            [InlineKeyboardButton("Informasi Bot", callback_data='bot_info')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = (
            "🤖 *Castile Money Bot - Bot Penghasil Saldo E-Wallet*\n"
            "💰 *Dapatkan saldo DANA dengan mudah:*\n"
            "• Hanya dengan menonton iklan 15 detik\n"
            "• Minimal withdraw Rp 5.000\n"
            "• Pembayaran instan ke e-wallet\n\n"
            "✨ *Fitur Utama:*\n"
            "• Tonton iklan dapat saldo\n"
            "• Withdraw ke DANA\n"
            "• Cek saldo realtime\n"
            "• Sistem otomatis 24 jam\n\n"
            "🌟 _Start sekarang dan mulai menghasilkan!_\n"
        )
        
        await query.edit_message_text(
            text=message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

# Fungsi untuk proses penarikan DANA
@rate_limit(300)  # Rate limit 5 menit untuk mencegah spam penarikan
async def process_dana(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "❌ Format salah. Gunakan: `/dana 08xxxxxxxxxx`",
            parse_mode='Markdown'
        )
        return
    
    dana_number = context.args[0]
    
    # Validasi nomor DANA (harus angka dan panjang 10-13 digit)
    if not dana_number.isdigit() or not (10 <= len(dana_number) <= 13):
        await update.message.reply_text(
            "❌ Nomor DANA tidak valid. Pastikan format benar.",
            parse_mode='Markdown'
        )
        return
    
    # Ambil saldo dari database
    conn = sqlite3.connect('castile_money.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    
    if not result or result[0] < 5000:
        await update.message.reply_text(
            "❌ Saldo Anda belum mencukupi untuk penarikan.\nMinimal penarikan adalah Rp5.000."
        )
        conn.close()
        return
    
    balance = result[0]
    
    # Proses penarikan (dalam implementasi nyata, ini akan terhubung ke sistem pembayaran)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Kurangi saldo
    cursor.execute("UPDATE users SET balance = 0 WHERE user_id = ?", (user_id,))
    
    # Catat transaksi
    cursor.execute(
        "INSERT INTO transactions (user_id, amount, type, status, details, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, balance, "withdraw", "pending", f"Withdrawal to DANA {dana_number}", now)
    )
    
    # Dapatkan ID transaksi
    cursor.execute("SELECT last_insert_rowid()")
    transaction_id = cursor.fetchone()[0]
    
    conn.commit()
    conn.close()
    
    # Kirim notifikasi ke admin (dalam implementasi nyata)
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"🔔 *Permintaan Penarikan Baru*\n\n"
                     f"Transaction ID: {transaction_id}\n"
                     f"User ID: {user_id}\n"
                     f"Jumlah: Rp{balance:,}\n"
                     f"DANA: {dana_number}\n"
                     f"Waktu: {now}\n\n"
                     f"Untuk menyetujui: `/approve {transaction_id}`\n"
                     f"Untuk menolak: `/reject {transaction_id} [alasan]`",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id}: {e}")
    
    # Kirim konfirmasi ke pengguna
    await update.message.reply_text(
        f"✅ *Permintaan Penarikan Berhasil*\n\n"
        f"Transaction ID: {transaction_id}\n"
        f"Jumlah: Rp{balance:,}\n"
        f"DANA: {dana_number}\n\n"
        f"Pembayaran akan diproses dalam 24 jam kerja.",
        parse_mode='Markdown'
    )

# Fungsi admin untuk menyetujui penarikan
@admin_only
async def approve_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "❌ Format salah. Gunakan: `/approve [transaction_id]`",
            parse_mode='Markdown'
        )
        return
    
    try:
        transaction_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID transaksi harus berupa angka.")
        return
    
    # Update status transaksi
    conn = sqlite3.connect('castile_money.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT user_id, amount, details FROM transactions WHERE id = ? AND type = 'withdraw' AND status = 'pending'", 
                  (transaction_id,))
    transaction = cursor.fetchone()
    
    if not transaction:
        await update.message.reply_text("❌ Transaksi tidak ditemukan atau sudah diproses.")
        conn.close()
        return
    
    user_id, amount, details = transaction
    
    # Update status transaksi
    cursor.execute("UPDATE transactions SET status = 'completed' WHERE id = ?", (transaction_id,))
    conn.commit()
    conn.close()
    
    # Notifikasi ke pengguna
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"💰 *Penarikan Berhasil*\n\n"
                 f"Transaction ID: {transaction_id}\n"
                 f"Jumlah: Rp{amount:,}\n"
                 f"Detail: {details}\n\n"
                 f"Terima kasih telah menggunakan Castile Money Bot!",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Failed to notify user {user_id}: {e}")
    
    await update.message.reply_text(f"✅ Penarikan ID {transaction_id} telah disetujui dan pengguna telah diberitahu.")

# Fungsi admin untuk menolak penarikan
@admin_only
async def reject_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ Format salah. Gunakan: `/reject [transaction_id] [alasan]`",
            parse_mode='Markdown'
        )
        return
    
    try:
        transaction_id = int(context.args[0])
        reason = " ".join(context.args[1:])
    except ValueError:
        await update.message.reply_text("❌ ID transaksi harus berupa angka.")
        return
    
    # Update status transaksi dan kembalikan saldo
    conn = sqlite3.connect('castile_money.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT user_id, amount FROM transactions WHERE id = ? AND type = 'withdraw' AND status = 'pending'", 
                  (transaction_id,))
    transaction = cursor.fetchone()
    
    if not transaction:
        await update.message.reply_text("❌ Transaksi tidak ditemukan atau sudah diproses.")
        conn.close()
        return
    
    user_id, amount = transaction
    
    # Update status transaksi
    cursor.execute("UPDATE transactions SET status = 'rejected', details = details || ' - Rejected: ' || ? WHERE id = ?", 
                  (reason, transaction_id))
    
    # Kembalikan saldo ke pengguna
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    
    conn.commit()
    conn.close()
    
    # Notifikasi ke pengguna
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"❌ *Penarikan Ditolak*\n\n"
                 f"Transaction ID: {transaction_id}\n"
                 f"Jumlah: Rp{amount:,}\n"
                 f"Alasan: {reason}\n\n"
                 f"Saldo telah dikembalikan ke akun Anda.",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Failed to notify user {user_id}: {e}")
    
    await update.message.reply_text(f"✅ Penarikan ID {transaction_id} telah ditolak dan saldo telah dikembalikan ke pengguna.")

# Fungsi admin untuk menambah saldo pengguna
@admin_only
async def add_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ Format salah. Gunakan: `/add_balance [user_id] [jumlah]`",
            parse_mode='Markdown'
        )
        return
    
    try:
        target_user_id = int(context.args[0])
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ User ID dan jumlah harus berupa angka.")
        return
    
    if amount <= 0:
        await update.message.reply_text("❌ Jumlah harus lebih dari 0.")
        return
    
    # Tambah saldo ke pengguna
    conn = sqlite3.connect('castile_money.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT username FROM users WHERE user_id = ?", (target_user_id,))
    user = cursor.fetchone()
    
    if not user:
        await update.message.reply_text("❌ Pengguna tidak ditemukan.")
        conn.close()
        return
    
    # Update saldo
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, target_user_id))
    
    # Catat transaksi
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "INSERT INTO transactions (user_id, amount, type, status, details, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
        (target_user_id, amount, "admin_add", "completed", f"Added by admin {update.effective_user.id}", now)
    )
    
    conn.commit()
    conn.close()
    
        # Notifikasi ke pengguna
    try:
        await context.bot.send_message(
            chat_id=target_user_id,
            text=f"💰 *Saldo Ditambahkan*\n\n"
                 f"Jumlah: Rp{amount:,}\n\n"
                 f"Saldo telah ditambahkan ke akun Anda.",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Failed to notify user {target_user_id}: {e}")
    
    await update.message.reply_text(f"✅ Saldo Rp{amount:,} telah ditambahkan ke pengguna {user[0]}.")

# Fungsi admin untuk melihat statistik bot
@admin_only
async def get_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('castile_money.db')
    cursor = conn.cursor()
    
    # Total pengguna
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    
    # Pengguna aktif (aktif dalam 7 hari terakhir)
    seven_days_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("SELECT COUNT(*) FROM users WHERE last_active > ?", (seven_days_ago,))
    active_users = cursor.fetchone()[0]
    
    # Total transaksi
    cursor.execute("SELECT COUNT(*) FROM transactions")
    total_transactions = cursor.fetchone()[0]
    
    # Total penarikan berhasil
    cursor.execute("SELECT COUNT(*), SUM(amount) FROM transactions WHERE type = 'withdraw' AND status = 'completed'")
    withdraw_result = cursor.fetchone()
    total_withdrawals = withdraw_result[0] or 0
    total_withdrawn = withdraw_result[1] or 0
    
    # Total saldo dalam sistem
    cursor.execute("SELECT SUM(balance) FROM users")
    total_balance = cursor.fetchone()[0] or 0
    
    conn.close()
    
    message = (
        f"📊 *Statistik Bot*\n\n"
        f"👥 Total Pengguna: {total_users}\n"
        f"👤 Pengguna Aktif (7 hari): {active_users}\n"
        f"🔄 Total Transaksi: {total_transactions}\n"
        f"💸 Total Penarikan: {total_withdrawals} (Rp{total_withdrawn:,})\n"
        f"💰 Total Saldo Sistem: Rp{total_balance:,}\n\n"
        f"Diperbarui: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    await update.message.reply_text(message, parse_mode='Markdown')

# Fungsi admin untuk broadcast pesan ke semua pengguna
@admin_only
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❌ Format salah. Gunakan: `/broadcast [pesan]`",
            parse_mode='Markdown'
        )
        return
    
    message = " ".join(context.args)
    
    # Ambil semua pengguna
    conn = sqlite3.connect('castile_money.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()
    
    # Kirim pesan ke semua pengguna
    success = 0
    failed = 0
    
    await update.message.reply_text(f"🔄 Memulai broadcast ke {len(users)} pengguna...")
    
    for user in users:
        try:
            await context.bot.send_message(
                chat_id=user[0],
                text=f"📢 *Pengumuman*\n\n{message}",
                parse_mode='Markdown'
            )
            success += 1
        except Exception as e:
            logger.error(f"Failed to send broadcast to {user[0]}: {e}")
            failed += 1
    
    await update.message.reply_text(
        f"✅ Broadcast selesai!\n"
        f"Berhasil: {success}\n"
        f"Gagal: {failed}"
    )

# Fungsi untuk menangani perintah yang tidak dikenal
async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ Perintah tidak dikenal. Gunakan /start untuk memulai bot."
    )

# Fungsi utama
def main():
    # Inisialisasi database
    init_db()
    
    # Inisialisasi bot
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Tambahkan handler
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("myid", get_my_id))
    application.add_handler(CommandHandler("referral", referral_command))
    application.add_handler(CommandHandler("balance", check_balance_command))
    application.add_handler(CommandHandler("dana", process_dana))
    
    # Handler admin
    application.add_handler(CommandHandler("approve", approve_withdrawal))
    application.add_handler(CommandHandler("reject", reject_withdrawal))
    application.add_handler(CommandHandler("add_balance", add_balance))
    application.add_handler(CommandHandler("stats", get_stats))
    application.add_handler(CommandHandler("broadcast", broadcast))
    
    # Handler callback
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Handler untuk perintah yang tidak dikenal
    application.add_handler(CommandHandler("unknown", unknown))
    
    # Mulai bot
    application.run_polling()

if __name__ == "__main__":
    main()






























































