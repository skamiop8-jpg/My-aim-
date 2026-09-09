import telebot
from telebot import types
import sqlite3, random, time, threading
from datetime import datetime, timedelta
import hashlib
import json

TOKEN = "8938006107:AAFrE4oTA-OOivxoA_eors8VSc7ap16xaFs"
ADMIN_IDS = {5789420986}  # @SAIREXAIR

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
db = sqlite3.connect("bot.db", check_same_thread=False)
cur = db.cursor()

# Таблицы с новыми полями
cur.execute("""CREATE TABLE IF NOT EXISTS users(
id INTEGER PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 0,
plan TEXT DEFAULT 'Нет', expires TEXT DEFAULT '-',
ref_code TEXT, ref_by INTEGER, ref_count INTEGER DEFAULT 0,
level INTEGER DEFAULT 1, daily_bonus TEXT DEFAULT '-',
shield_active INTEGER DEFAULT 0, shield_uses INTEGER DEFAULT 0,
auto_renew INTEGER DEFAULT 0, skin TEXT DEFAULT '🟢',
quest_daily TEXT DEFAULT '-', quest_progress INTEGER DEFAULT 0,
total_jobs INTEGER DEFAULT 0, total_survived INTEGER DEFAULT 0)""")
cur.execute("""CREATE TABLE IF NOT EXISTS jobs(
id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, target TEXT,
target_type TEXT, reason TEXT, status TEXT, created TEXT,
ai_chance INTEGER DEFAULT 50, ai_time TEXT, completed TEXT,
shield_used INTEGER DEFAULT 0, final_chance INTEGER DEFAULT 0,
boosted INTEGER DEFAULT 0, boost_cost INTEGER DEFAULT 0)""")

# Миграция старой таблицы jobs: добавляем отсутствующие колонки
_jobs_columns = {
    "ai_chance": "INTEGER DEFAULT 50", "ai_time": "TEXT", "completed": "TEXT",
    "shield_used": "INTEGER DEFAULT 0", "final_chance": "INTEGER DEFAULT 0",
    "boosted": "INTEGER DEFAULT 0", "boost_cost": "INTEGER DEFAULT 0"
}
_existing_jobs = {row[1] for row in cur.execute("PRAGMA table_info(jobs)").fetchall()}
for _name, _definition in _jobs_columns.items():
    if _name not in _existing_jobs:
        cur.execute(f"ALTER TABLE jobs ADD COLUMN {_name} {_definition}")
db.commit()

cur.execute("""CREATE TABLE IF NOT EXISTS requests(
id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, text TEXT,
status TEXT, created TEXT)""")
cur.execute("""CREATE TABLE IF NOT EXISTS ref_purchases(
id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, ref_id INTEGER,
amount INTEGER, created TEXT)""")
cur.execute("""CREATE TABLE IF NOT EXISTS shield_purchases(
id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, cost INTEGER,
created TEXT)""")
cur.execute("""CREATE TABLE IF NOT EXISTS achievements(
id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT,
description TEXT, icon TEXT, created TEXT)""")
cur.execute("""CREATE TABLE IF NOT EXISTS cases_log(
id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, prize TEXT,
created TEXT)""")
cur.execute("""CREATE TABLE IF NOT EXISTS top_history(
id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, score INTEGER,
month TEXT)""")


# ===== Коммерческие функции =====
cur.execute("CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, item TEXT, amount INTEGER, status TEXT, created TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS promo_codes(code TEXT PRIMARY KEY, discount INTEGER DEFAULT 0, uses INTEGER DEFAULT 0, max_uses INTEGER DEFAULT 0)")
cur.execute("CREATE TABLE IF NOT EXISTS favorites(user_id INTEGER, item TEXT, UNIQUE(user_id,item))")
cur.execute("CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, rating INTEGER, text TEXT, created TEXT)")
db.commit()

def commercial_menu():
    k=types.InlineKeyboardMarkup(row_width=2)
    k.add(types.InlineKeyboardButton("💳 Баланс",callback_data="shop_balance"),types.InlineKeyboardButton("📦 Заказы",callback_data="shop_orders"))
    k.add(types.InlineKeyboardButton("❤️ Избранное",callback_data="shop_fav"),types.InlineKeyboardButton("🎟️ Промокод",callback_data="shop_promo"))
    k.add(types.InlineKeyboardButton("⭐ VIP",callback_data="shop_vip"),types.InlineKeyboardButton("◀️ Назад",callback_data="back_main"))
    return k

@bot.callback_query_handler(func=lambda c: c.data=="shop")
def shop(c):
    bot.edit_message_text("🛍 <b>Магазин</b>\n\nВыберите раздел:",c.message.chat.id,c.message.message_id,reply_markup=commercial_menu())

@bot.callback_query_handler(func=lambda c: c.data=="shop_balance")
def shop_balance(c):
    u=get_user(c.from_user.id,c.from_user.username or "")
    bot.answer_callback_query(c.id,f"💳 Баланс: {u[2] if u else 0}",show_alert=True)

@bot.callback_query_handler(func=lambda c: c.data=="shop_orders")
def shop_orders(c):
    rows=cur.execute("SELECT item,amount,status,created FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10",(c.from_user.id,)).fetchall()
    text="📦 <b>Мои заказы</b>\n\n"
    text += "\n".join(f"• {r[0]} — {r[1]} — {r[2]}\n  🕐 {r[3]}" for r in rows) if rows else "Заказов пока нет."
    bot.edit_message_text(text,c.message.chat.id,c.message.message_id,reply_markup=commercial_menu())

@bot.callback_query_handler(func=lambda c: c.data=="shop_fav")
def shop_fav(c):
    rows=cur.execute("SELECT item FROM favorites WHERE user_id=?",(c.from_user.id,)).fetchall()
    text="❤️ <b>Избранное</b>\n\n"+ ("\n".join("• "+r[0] for r in rows) if rows else "Пусто.")
    bot.edit_message_text(text,c.message.chat.id,c.message.message_id,reply_markup=commercial_menu())

@bot.callback_query_handler(func=lambda c: c.data=="shop_vip")
def shop_vip(c):
    u=get_user(c.from_user.id,c.from_user.username or "")
    plan=u[3] if u else "Нет"
    bot.edit_message_text(f"⭐ <b>VIP</b>\n\nТекущий тариф: <b>{plan}</b>\n\nVIP-уровень можно использовать для персональных скидок и приоритетной поддержки.",c.message.chat.id,c.message.message_id,reply_markup=commercial_menu())

@bot.callback_query_handler(func=lambda c: c.data=="shop_promo")
def shop_promo(c):
    m=bot.send_message(c.message.chat.id,"🎟️ Введите промокод:")
    bot.register_next_step_handler(m,apply_promo)

def apply_promo(m):
    code=m.text.strip().upper()
    row=cur.execute("SELECT discount,uses,max_uses FROM promo_codes WHERE code=?",(code,)).fetchone()
    if not row:
        bot.send_message(m.chat.id,"❌ Промокод не найден.")
    elif row[2] and row[1]>=row[2]:
        bot.send_message(m.chat.id,"❌ Лимит использования промокода исчерпан.")
    else:
        cur.execute("UPDATE promo_codes SET uses=uses+1 WHERE code=?",(code,)); db.commit()
        bot.send_message(m.chat.id,f"✅ Промокод применён. Скидка: <b>{row[0]}%</b>")

db.commit()

# Миграция старой базы: добавляем недостающие поля users
_user_columns = {
    "username": "TEXT", "balance": "INTEGER DEFAULT 0", "plan": "TEXT DEFAULT 'Нет'",
    "expires": "TEXT DEFAULT '-'", "ref_code": "TEXT", "ref_by": "INTEGER",
    "ref_count": "INTEGER DEFAULT 0", "level": "INTEGER DEFAULT 1",
    "daily_bonus": "TEXT DEFAULT '-'", "shield_active": "INTEGER DEFAULT 0",
    "shield_uses": "INTEGER DEFAULT 0", "auto_renew": "INTEGER DEFAULT 0",
    "skin": "TEXT DEFAULT '🟢'", "quest_daily": "TEXT DEFAULT '-'",
    "quest_progress": "INTEGER DEFAULT 0", "total_jobs": "INTEGER DEFAULT 0",
    "total_survived": "INTEGER DEFAULT 0"
}
_existing = {row[1] for row in cur.execute("PRAGMA table_info(users)").fetchall()}
for _name, _definition in _user_columns.items():
    if _name not in _existing:
        cur.execute(f"ALTER TABLE users ADD COLUMN {_name} {_definition}")
db.commit()

# Генерация реферального кода
def generate_ref_code(uid):
    return hashlib.md5(str(uid).encode()).hexdigest()[:8]

# Получить пользователя
def get_user(uid, username=""):
    # Всегда возвращаем поля users в одном и том же порядке.
    columns = "id,username,balance,plan,expires,ref_code,ref_by,ref_count,level,daily_bonus,shield_active,shield_uses,auto_renew,skin,quest_daily,quest_progress,total_jobs,total_survived"
    u = cur.execute(f"SELECT {columns} FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        ref_code = generate_ref_code(uid)
        cur.execute("INSERT INTO users(id,username,ref_code) VALUES(?,?,?)", (uid, username, ref_code))
        db.commit()
    return cur.execute(f"SELECT {columns} FROM users WHERE id=?", (uid,)).fetchone()

# Проверка админа
def is_admin(uid):
    return uid in ADMIN_IDS

# Проверка подписки
def has_subscription(uid):
    if is_admin(uid):
        return True
    u = get_user(uid)
    plan = u[3]
    expires = u[4]
    if plan == "Нет" or plan is None:
        return False
    if plan == "Lifetime":
        return True
    try:
        exp_date = datetime.strptime(expires, "%d.%m.%Y")
        return datetime.now() <= exp_date
    except:
        return False

# Скорость сноса в зависимости от тарифа
def get_delete_time(plan):
    times = {
        "Basic": (30, 60),
        "Standard": (45, 90),
        "Premium": (60, 120),
        "PRO": (120, 240),
        "Lifetime": (240, 480),
        "Админ": (60, 180)
    }
    return times.get(plan, (30, 60))

# AI анализ риска сноса
def ai_risk_analysis(target_type, target, plan="Basic"):
    base_chance = {
        "account": 55,
        "group": 50,
        "channel": 45,
        "bot": 60,
        "message": 40,
        "link": 35
    }.get(target_type, 50)
    
    plan_mod = {
        "Basic": 1.0,
        "Standard": 1.15,
        "Premium": 1.3,
        "PRO": 1.5,
        "Lifetime": 1.8
    }.get(plan, 1.0)
    
    chance = int(base_chance * plan_mod)
    chance += random.randint(-10, 15)
    chance = max(10, min(95, chance))
    
    min_t, max_t = get_delete_time(plan)
    minutes = random.randint(min_t, max_t)
    
    if minutes < 60:
        time_str = f"{minutes} мин"
    elif minutes < 1440:
        hours = minutes // 60
        mins = minutes % 60
        time_str = f"{hours} ч {mins} мин"
    else:
        days = minutes // 1440
        hours = (minutes % 1440) // 60
        time_str = f"{days} д {hours} ч"
    
    return chance, time_str

# AI комментарий
def ai_comment(chance, plan):
    comments = {
        "Basic": "💡 Базовый тариф. Рекомендуем улучшить защиту.",
        "Standard": "📊 Стандартный анализ. Есть шансы.",
        "Premium": "🛡️ Премиум защита активна.",
        "PRO": "⚡ PRO-уровень. Максимальная эффективность.",
        "Lifetime": "👑 Бессрочный доступ. Приоритетная обработка.",
        "Админ": "👑 Администратор. Приоритет."
    }
    if is_admin(plan) if isinstance(plan, int) else False:
        plan = "Админ"
    
    comment = comments.get(plan, "Обычный анализ.")
    
    if chance > 80:
        return f"🔴 {comment} Риск очень высокий!"
    elif chance > 60:
        return f"🟠 {comment} Риск выше среднего."
    elif chance > 40:
        return f"🟡 {comment} Средний риск."
    elif chance > 20:
        return f"🟢 {comment} Низкий риск."
    else:
        return f"✅ {comment} Минимальный риск!"

# Проверка достижений
def check_achievements(uid):
    u = get_user(uid)
    jobs_count = cur.execute("SELECT COUNT(*) FROM jobs WHERE user_id=?", (uid,)).fetchone()[0]
    survived = cur.execute("SELECT COUNT(*) FROM jobs WHERE user_id=? AND status='✅ Выжило'", (uid,)).fetchone()[0]
    ref_count = u[7]
    shield_uses = u[11]
    level = u[8]
    
    achievements = []
    
    # Достижения
    if jobs_count >= 1:
        achievements.append(("first_job", "🏆 Первая работа!", "Создана первая работа", "🏆"))
    if jobs_count >= 10:
        achievements.append(("job_master", "💪 Мастер работ", "Создано 10 работ", "💪"))
    if jobs_count >= 50:
        achievements.append(("job_legend", "⭐ Легенда", "Создано 50 работ", "⭐"))
    if jobs_count >= 100:
        achievements.append(("job_god", "👑 Бог работ", "Создано 100 работ", "👑"))
    
    if survived >= 5:
        achievements.append(("survivor", "🛡️ Выживший", "5 работ выжило", "🛡️"))
    if survived >= 25:
        achievements.append(("survivor_master", "🛡️ Мастер выживания", "25 работ выжило", "🛡️"))
    
    if ref_count >= 1:
        achievements.append(("ref_first", "👥 Первый реферал", "Приглашён первый друг", "👥"))
    if ref_count >= 10:
        achievements.append(("ref_master", "👥 Мастер рефералов", "Приглашено 10 друзей", "👥"))
    if ref_count >= 50:
        achievements.append(("ref_king", "👑 Король рефералов", "Приглашено 50 друзей", "👑"))
    
    if shield_uses >= 1:
        achievements.append(("shield_first", "🛡️ Защитник", "Использована первая защита", "🛡️"))
    if shield_uses >= 10:
        achievements.append(("shield_master", "🛡️ Мастер защиты", "Использовано 10 защит", "🛡️"))
    
    if level >= 3:
        achievements.append(("level_up", "🌟 Эксперт", "Достигнут 3 уровень", "🌟"))
    if level >= 5:
        achievements.append(("level_legend", "👑 Легенда", "Достигнут 5 уровень", "👑"))
    
    # Сохраняем достижения
    for name, title, desc, icon in achievements:
        exists = cur.execute("SELECT * FROM achievements WHERE user_id=? AND name=?", (uid, name)).fetchone()
        if not exists:
            cur.execute("INSERT INTO achievements(user_id,name,description,icon,created) VALUES(?,?,?,?,?)",
                       (uid, title, desc, icon, datetime.now().strftime("%d.%m.%Y %H:%M")))
            db.commit()
            try:
                bot.send_message(uid, f"🎉 <b>Новое достижение!</b>\n\n{icon} <b>{title}</b>\n{desc}")
            except:
                pass

# Генерация ежедневного квеста
def generate_quest(uid):
    quests = [
        ("Создайте 3 работы", 3, 15),
        ("Пригласите 1 друга", 1, 10),
        ("Используйте защиту", 1, 20),
        ("Создайте 5 работ", 5, 25),
        ("Выживите 2 работы", 2, 30),
        ("Купите защиту", 1, 15),
        ("Создайте работу типа 'Аккаунт'", 1, 12)
    ]
    quest, target, reward = random.choice(quests)
    quest_data = f"{quest}|{target}|{reward}"
    cur.execute("UPDATE users SET quest_daily=? WHERE id=?", (quest_data, uid))
    db.commit()
    return quest, target, reward

# Меню
def menu(uid):
    k = types.InlineKeyboardMarkup(row_width=2)
    if has_subscription(uid) or is_admin(uid):
        k.add(types.InlineKeyboardButton("💥 Создать работу", callback_data="create"),
              types.InlineKeyboardButton("📋 Мои работы", callback_data="jobs"))
    else:
        k.add(types.InlineKeyboardButton("🔒 Доступ заблокирован", callback_data="no_access"))
    k.add(types.InlineKeyboardButton("👤 Профиль", callback_data="profile"),
          types.InlineKeyboardButton("💎 Подписка", callback_data="plans"))
    k.add(types.InlineKeyboardButton("📨 Запросы", callback_data="requests"),
          types.InlineKeyboardButton("🆘 Поддержка", callback_data="support"))
    k.add(types.InlineKeyboardButton("👥 Рефералы", callback_data="ref"),
          types.InlineKeyboardButton("📖 Инструкция", callback_data="instruction"))
    k.add(types.InlineKeyboardButton("🏆 ТОП", callback_data="top"),
          types.InlineKeyboardButton("🎁 Кейсы", callback_data="cases"))
    if is_admin(uid):
        k.add(types.InlineKeyboardButton("⚙️ Админ-панель", callback_data="admin"))
    return k

def back():
    k = types.InlineKeyboardMarkup()
    k.add(types.InlineKeyboardButton("◀️ Назад", callback_data="back"))
    return k

# START
@bot.message_handler(commands=["start"])
def start(m):
    uid = m.from_user.id
    get_user(uid, m.from_user.username or "")
    
    # Проверка реферальной ссылки
    if " " in m.text:
        ref = m.text.split()[1]
        if ref.isdigit() and int(ref) != uid:
            u = get_user(int(ref))
            if u:
                cur.execute("UPDATE users SET ref_by=? WHERE id=?", (int(ref), uid))
                cur.execute("UPDATE users SET ref_count=ref_count+1 WHERE id=?", (int(ref),))
                db.commit()
                bot.send_message(m.chat.id, f"✅ Вы зарегистрированы по реферальной ссылке @{u[1]}! 🎉")
                try:
                    bot.send_message(int(ref), f"👥 Новый реферал! @{m.from_user.username or m.from_user.first_name}")
                except:
                    pass
    
    # Проверяем достижения
    check_achievements(uid)
    
    text = f"""<b>⚡ Control Center</b>

Добро пожаловать, <b>{m.from_user.first_name}</b>.

💥 <b>Работы</b> — создание заданий
👤 <b>Профиль</b> — аккаунт и доступ
💎 <b>Подписка</b> — тарифы
📨 <b>Запросы</b> — обращения
🆘 <b>Поддержка</b> — помощь
👥 <b>Рефералы</b> — зарабатывай!
📖 <b>Инструкция</b> — как всё работает
🏆 <b>ТОП</b> — рейтинг лидеров
🎁 <b>Кейсы</b> — рулетка с призами

<i>ID: {m.from_user.id}</i>"""
    try:
        with open("start.jpg", "rb") as f:
            bot.send_photo(m.chat.id, f, caption=text, reply_markup=menu(uid))
    except FileNotFoundError:
        bot.send_message(m.chat.id, text, reply_markup=menu(uid))

# ПРОФИЛЬ
@bot.callback_query_handler(func=lambda c: c.data == "profile")
def profile(c):
    u = get_user(c.from_user.id)
    sub_status = "✅ Активна" if has_subscription(c.from_user.id) else "❌ Неактивна"
    if is_admin(c.from_user.id):
        sub_status = "👑 Админ (бесплатно)"
    
    today = datetime.now().strftime("%d.%m.%Y")
    bonus_text = ""
    if u[9] != today:
        bonus_text = "\n\n🎁 <b>Ежедневный бонус доступен!</b>"
    
    # Проверяем квест
    quest_text = ""
    if u[14] != today:
        quest, target, reward = generate_quest(c.from_user.id)
        quest_text = f"\n\n📋 <b>Ежедневный квест:</b>\n{quest} → {reward}💰"
    else:
        quest_data = u[14]
        if "|" in quest_data:
            parts = quest_data.split("|")
            if len(parts) >= 3:
                quest_text = f"\n\n📋 <b>Квест на сегодня:</b>\n{parts[0]} → {parts[2]}💰"
    
    level_names = {1: "🌱 Новичок", 2: "🌿 Активный", 3: "🌳 Мастер", 4: "🌟 Эксперт", 5: "👑 Легенда"}
    shield_text = f"🛡️ Защит: <b>{u[10]}</b>" if u[10] > 0 else "🛡️ Защита не активна"
    auto_renew_text = "🔁 Автопродление: " + ("✅ Вкл" if u[12] == 1 else "❌ Выкл")
    
    bot.edit_message_text(f"""<b>👤 Профиль</b>

{level_names.get(u[8], "🌱 Новичок")} {u[13]}

🆔 ID: <code>{u[0]}</code>
👤 @{u[1] or "не указан"}
💰 Баланс: <b>{u[2]} кредитов</b>
💎 Тариф: <b>{u[3]}</b>
⏳ До: <b>{u[4]}</b>
📊 Статус подписки: <b>{sub_status}</b>
{shield_text}
{auto_renew_text}
🎯 Всего работ: <b>{u[16]}</b>
✅ Выжило: <b>{u[17]}</b>
👥 Рефералов: <b>{u[7]}</b>
{quest_text}{bonus_text}""", 
c.message.chat.id, c.message.message_id, 
reply_markup=types.InlineKeyboardMarkup(row_width=2).add(
    types.InlineKeyboardButton("🎁 Бонус", callback_data="daily_bonus"),
    types.InlineKeyboardButton("🛡️ Купить защиту", callback_data="buy_shield_menu"),
    types.InlineKeyboardButton("🔁 Автопродление", callback_data="toggle_renew"),
    types.InlineKeyboardButton("🏆 Достижения", callback_data="achievements"),
    types.InlineKeyboardButton("◀️ Назад", callback_data="back")
))

# АВТОПРОДЛЕНИЕ
@bot.callback_query_handler(func=lambda c: c.data == "toggle_renew")
def toggle_renew(c):
    u = get_user(c.from_user.id)
    new_status = 0 if u[12] == 1 else 1
    cur.execute("UPDATE users SET auto_renew=? WHERE id=?", (new_status, c.from_user.id))
    db.commit()
    status_text = "включено" if new_status == 1 else "выключено"
    bot.answer_callback_query(c.id, f"✅ Автопродление {status_text}!", show_alert=True)
    profile(c)

# ДОСТИЖЕНИЯ
@bot.callback_query_handler(func=lambda c: c.data == "achievements")
def achievements(c):
    rows = cur.execute("SELECT icon,name,description,created FROM achievements WHERE user_id=? ORDER BY id DESC", (c.from_user.id,)).fetchall()
    text = "<b>🏆 Достижения</b>\n\n"
    if not rows:
        text += "У вас пока нет достижений. Создавайте работы и зарабатывайте их!"
    else:
        for r in rows:
            text += f"{r[0]} <b>{r[1]}</b>\n{r[2]}\n🕐 {r[3]}\n\n"
    
    k = types.InlineKeyboardMarkup()
    k.add(types.InlineKeyboardButton("◀️ Назад", callback_data="back"))
    bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=k)

# ЕЖЕДНЕВНЫЙ БОНУС
@bot.callback_query_handler(func=lambda c: c.data == "daily_bonus")
def daily_bonus(c):
    u = get_user(c.from_user.id)
    today = datetime.now().strftime("%d.%m.%Y")
    
    if u[9] == today:
        return bot.answer_callback_query(c.id, "❌ Вы уже получили бонус сегодня!", show_alert=True)
    
    # Проверяем квест
    quest_completed = False
    quest_reward = 0
    if u[14] != today:
        # Генерируем новый квест
        quest, target, reward = generate_quest(c.from_user.id)
        quest_reward = reward
    else:
        quest_data = u[14]
        if "|" in quest_data:
            parts = quest_data.split("|")
            if len(parts) >= 3:
                # Проверяем выполнение квеста
                progress = u[15] if u[15] else 0
                if progress >= int(parts[1]):
                    quest_completed = True
                    quest_reward = int(parts[2])
    
    bonus = random.randint(10, 30)
    total_bonus = bonus + (quest_reward if quest_completed else 0)
    
    cur.execute("UPDATE users SET balance=balance+?, daily_bonus=? WHERE id=?", (total_bonus, today, c.from_user.id))
    db.commit()
    
    bonus_text = f"💰 Основной бонус: +{bonus} кредитов"
    if quest_completed:
        bonus_text += f"\n✅ Квест выполнен! +{quest_reward} кредитов"
    else:
        bonus_text += f"\n📋 Выполните квест, чтобы получить бонус!"
    
    bot.answer_callback_query(c.id, f"🎉 +{total_bonus} кредитов!\n{bonus_text}", show_alert=True)
    profile(c)

# КЕЙСЫ
@bot.callback_query_handler(func=lambda c: c.data == "cases")
def cases_menu(c):
    u = get_user(c.from_user.id)
    text = """<b>🎁 Кейсы</b>

Откройте кейс и получите случайный приз!

<b>Цена открытия:</b> 25 кредитов

<b>Возможные призы:</b>
💰 10-50 кредитов
🛡️ 1-3 защиты
⭐ 1-3 дня подписки (Basic)
🏆 Редкие достижения
💎 Скидка 20% на подписку

<b>Ваш баланс:</b> {} кредитов""".format(u[2])
    
    k = types.InlineKeyboardMarkup(row_width=2)
    k.add(types.InlineKeyboardButton("🎲 Открыть кейс (25💰)", callback_data="open_case"),
          types.InlineKeyboardButton("📊 История кейсов", callback_data="case_history"))
    k.add(types.InlineKeyboardButton("◀️ Назад", callback_data="back"))
    bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=k)

@bot.callback_query_handler(func=lambda c: c.data == "open_case")
def open_case(c):
    u = get_user(c.from_user.id)
    if u[2] < 25:
        return bot.answer_callback_query(c.id, "❌ Недостаточно кредитов! Нужно 25", show_alert=True)
    
    cur.execute("UPDATE users SET balance=balance-25 WHERE id=?", (c.from_user.id,))
    
    # Рандомный приз
    prizes = [
        ("💰 10 кредитов", 10),
        ("💰 20 кредитов", 20),
        ("💰 30 кредитов", 30),
        ("💰 50 кредитов", 50),
        ("🛡️ 1 защита", "shield_1"),
        ("🛡️ 2 защиты", "shield_2"),
        ("🛡️ 3 защиты", "shield_3"),
        ("⭐ 1 день подписки", "day_1"),
        ("⭐ 3 дня подписки", "day_3"),
        ("🏆 Редкое достижение", "rare_ach"),
        ("💎 Скидка 20%", "discount")
    ]
    
    prize_name, prize_value = random.choice(prizes)
    
    # Применяем приз
    prize_text = ""
    if isinstance(prize_value, int):
        cur.execute("UPDATE users SET balance=balance+? WHERE id=?", (prize_value, c.from_user.id))
        prize_text = f"✅ Вы получили {prize_name}!"
    elif "shield" in str(prize_value):
        count = int(str(prize_value).split("_")[1])
        cur.execute("UPDATE users SET shield_active=shield_active+? WHERE id=?", (count, c.from_user.id))
        prize_text = f"✅ Вы получили {prize_name}!"
    elif "day" in str(prize_value):
        days = int(str(prize_value).split("_")[1])
        if u[3] != "Нет" and u[4] != "-":
            try:
                exp_date = datetime.strptime(u[4], "%d.%m.%Y")
                new_exp = exp_date + timedelta(days=days)
                cur.execute("UPDATE users SET expires=? WHERE id=?", (new_exp.strftime("%d.%m.%Y"), c.from_user.id))
            except:
                new_exp = datetime.now() + timedelta(days=days)
                cur.execute("UPDATE users SET plan='Basic', expires=? WHERE id=?", (new_exp.strftime("%d.%m.%Y"), c.from_user.id))
        else:
            new_exp = datetime.now() + timedelta(days=days)
            cur.execute("UPDATE users SET plan='Basic', expires=? WHERE id=?", (new_exp.strftime("%d.%m.%Y"), c.from_user.id))
        prize_text = f"✅ Вы получили {prize_name}!"
    elif "rare" in str(prize_value):
        cur.execute("INSERT INTO achievements(user_id,name,description,icon,created) VALUES(?,?,?,?,?)",
                   (c.from_user.id, "🎁 Удача", "Открыт редкий кейс", "🎁", datetime.now().strftime("%d.%m.%Y %H:%M")))
        db.commit()
        prize_text = "🎁 Вы получили редкое достижение 'Удача'!"
    elif "discount" in str(prize_value):
        cur.execute("UPDATE users SET balance=balance+5 WHERE id=?", (c.from_user.id,))
        prize_text = f"💎 Вы получили скидку 20% на подписку! (зачислено 5 кредитов)"
    
    cur.execute("INSERT INTO cases_log(user_id,prize,created) VALUES(?,?,?)",
               (c.from_user.id, prize_name, datetime.now().strftime("%d.%m.%Y %H:%M")))
    db.commit()
    
    bot.answer_callback_query(c.id, prize_text, show_alert=True)
    cases_menu(c)

@bot.callback_query_handler(func=lambda c: c.data == "case_history")
def case_history(c):
    rows = cur.execute("SELECT prize,created FROM cases_log WHERE user_id=? ORDER BY id DESC LIMIT 10", (c.from_user.id,)).fetchall()
    text = "<b>📊 История кейсов</b>\n\n"

    if not rows:
        text += "Вы ещё не открывали кейсы."
    else:
        for r in rows:
            text += f"🎲 {r[0]}\n🕐 {r[1]}\n\n"
    
    k = types.InlineKeyboardMarkup()
    k.add(types.InlineKeyboardButton("◀️ Назад", callback_data="cases"))
    bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=k)

# ТОП
@bot.callback_query_handler(func=lambda c: c.data == "top")
def top(c):
    # Топ по работам
    top_users = cur.execute("""SELECT id,username,total_jobs,total_survived,level 
                              FROM users WHERE total_jobs > 0 ORDER BY total_jobs DESC LIMIT 10""").fetchall()
    
    text = "<b>🏆 ТОП пользователей</b>\n\n"
    medals = ["🥇", "🥈", "🥉"]
    
    for i, r in enumerate(top_users):
        medal = medals[i] if i < 3 else f"{i+1}."
        username = f"@{r[1]}" if r[1] else f"ID:{r[0]}"
        level_names = {1: "🌱", 2: "🌿", 3: "🌳", 4: "🌟", 5: "👑"}
        text += f"{medal} {level_names.get(r[4], '🌱')} {username}\n📊 Работ: {r[2]}, Выжило: {r[3]}\n\n"
    
    k = types.InlineKeyboardMarkup()
    k.add(types.InlineKeyboardButton("◀️ Назад", callback_data="back"))
    bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=k)

# ИНСТРУКЦИЯ
@bot.callback_query_handler(func=lambda c: c.data == "instruction")
def instruction(c):
    text = """<b>📖 Инструкция по использованию</b>

🔹 <b>Что такое Control Center?</b>
Сервис для проверки и анализа аккаунтов, каналов и групп.

🔹 <b>Как создать работу?</b>
1. Нажмите «Создать работу»
2. Выберите тип цели
3. Отправьте ссылку или username
4. Укажите причину
5. Получите AI-анализ

🔹 <b>Ускорение работ!</b>
⚡ Можно ускорить работу за кредиты:
• Ускорение в 2 раза — 20 кредитов
• Мгновенное завершение — 50 кредитов

🔹 <b>Что такое AI-анализ?</b>
Наш ИИ анализирует:
• Тип цели
• Возраст аккаунта
• Статистику
• Риск блокировки

🔹 <b>Защита от сноса</b>
🛡️ Anti-Delete Shield повышает шанс выживания на 5-25%

🔹 <b>Ежедневные квесты</b>
📋 Выполняйте квесты и получайте дополнительные кредиты!

🔹 <b>Кейсы</b>
🎁 Открывайте кейсы за 25 кредитов и получайте призы!

🔹 <b>Автопродление</b>
🔁 Включите автопродление подписки и не переживайте о сроке!

🔹 <b>Достижения</b>
🏆 Зарабатывайте достижения за активность!

🔹 <b>Рефералы</b>
👥 Приглашайте друзей и получайте 20% от их покупок!

<b>Поддержка:</b> @SAIREXAIR"""
    
    k = types.InlineKeyboardMarkup()
    k.add(types.InlineKeyboardButton("🛡️ Купить защиту", callback_data="buy_shield_menu"))
    k.add(types.InlineKeyboardButton("⚡ Ускорить работу", callback_data="boost_info"))
    k.add(types.InlineKeyboardButton("◀️ Назад", callback_data="back"))
    bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=k)

# УСКОРЕНИЕ РАБОТ
@bot.callback_query_handler(func=lambda c: c.data == "boost_info")
def boost_info(c):
    text = """<b>⚡ Ускорение работ</b>

Ускорьте выполнение вашей работы!

<b>Доступные варианты:</b>
🚀 <b>Быстрое ускорение</b> — 20 кредитов
   Время выполнения сокращается в 2 раза

💫 <b>Мгновенное завершение</b> — 50 кредитов
   Работа завершается сразу!

<b>Как ускорить?</b>
1. Создайте работу
2. Нажмите «Ускорить» в меню работы
3. Выберите тип ускорения

<b>Важно!</b>
• Ускорение доступно только для активных подписок
• Ускорить можно только 1 раз за работу
• При ускорении AI-анализ не меняется"""
    
    k = types.InlineKeyboardMarkup()
    k.add(types.InlineKeyboardButton("◀️ Назад", callback_data="instruction"))
    bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=k)

# ПОКУПКА ЗАЩИТЫ
@bot.callback_query_handler(func=lambda c: c.data == "buy_shield_menu")
def buy_shield_menu(c):
    u = get_user(c.from_user.id)
    text = f"""<b>🛡️ Anti-Delete Shield</b>

Защита от сноса для ваших работ!

📊 <b>Увеличивает шанс выживания</b> на 5-25%
⚡ <b>Приоритетная обработка</b>
🔄 <b>Автоматическое применение</b>

<b>Ваш баланс:</b> {u[2]} кредитов
<b>Активно защит:</b> {u[10]}

<b>Доступные пакеты:</b>
🔹 1 защита — 50 кредитов
🔹 3 защиты — 120 кредитов (экономия 30)
🔹 5 защит — 180 кредитов (экономия 70)"""

    k = types.InlineKeyboardMarkup(row_width=2)
    k.add(types.InlineKeyboardButton("1 шт - 50💰", callback_data="shield_1"),
          types.InlineKeyboardButton("3 шт - 120💰", callback_data="shield_3"),
          types.InlineKeyboardButton("5 шт - 180💰", callback_data="shield_5"))
    k.add(types.InlineKeyboardButton("◀️ Назад", callback_data="instruction"))
    bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=k)

@bot.callback_query_handler(func=lambda c: c.data.startswith("shield_"))
def buy_shield_pack(c):
    count = int(c.data.split("_")[1])
    prices = {1: 50, 3: 120, 5: 180}
    cost = prices[count]
    
    u = get_user(c.from_user.id)
    if u[2] < cost:
        return bot.answer_callback_query(c.id, f"❌ Недостаточно кредитов! Нужно {cost}, у вас {u[2]}", show_alert=True)
    
    cur.execute("UPDATE users SET balance=balance-?, shield_active=shield_active+? WHERE id=?", (cost, count, c.from_user.id))
    cur.execute("INSERT INTO shield_purchases(user_id, cost, created) VALUES(?,?,?)",
                (c.from_user.id, cost, datetime.now().strftime("%d.%m.%Y %H:%M")))
    db.commit()
    
    bot.answer_callback_query(c.id, f"✅ Куплено {count} защит! Баланс: {u[2]-cost}", show_alert=True)
    buy_shield_menu(c)

# АКТИВАЦИЯ ЗАЩИТЫ
def use_shield(uid):
    u = get_user(uid)
    if u[10] > 0:
        cur.execute("UPDATE users SET shield_active=shield_active-1, shield_uses=shield_uses+1 WHERE id=?", (uid,))
        db.commit()
        return True
    return False

# ТАРИФЫ
@bot.callback_query_handler(func=lambda c: c.data == "plans")
def plans(c):
    k = types.InlineKeyboardMarkup(row_width=1)
    for name, price, desc in [
        ("🟢 Basic", "$3 / 7 дней", "Базовый функционал"),
        ("🔵 Standard", "$7 / 30 дней", "Расширенный доступ"),
        ("🟣 Premium", "$15 / 30 дней", "Полный доступ + защита"),
        ("🔥 PRO", "$25 / 90 дней", "Максимальные возможности"),
        ("💎 Lifetime", "$50", "Навсегда + приоритет")
    ]:
        k.add(types.InlineKeyboardButton(f"{name} — {price}", callback_data="buy_" + name.split()[-1]))
    k.add(types.InlineKeyboardButton("◀️ Назад", callback_data="back"))
    bot.edit_message_text("""<b>💎 Тарифы</b>

Выберите уровень доступа:

🟢 <b>Basic</b> — базовый функционал
⏱ Скорость: 30-60 мин

🔵 <b>Standard</b> — расширенный доступ
⏱ Скорость: 45-90 мин

🟣 <b>Premium</b> — полный доступ
⏱ Скорость: 60-120 мин

🔥 <b>PRO</b> — максимальные возможности
⏱ Скорость: 120-240 мин

💎 <b>Lifetime</b> — навсегда + приоритет
⏱ Скорость: 240-480 мин

<b>Чем выше тариф — тем быстрее обработка!</b>

💰 <b>20% бонус на баланс</b> за покупку по реферальной ссылке!""", 
c.message.chat.id, c.message.message_id, reply_markup=k)

# ПОКУПКА ПОДПИСКИ
@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_"))
def buy(c):
    plan_name = c.data[4:]
    bot.answer_callback_query(c.id, "Заявка создана")
    
    u = get_user(c.from_user.id)
    
    # Начисление реферального бонуса
    if u[6] and u[6] != "-":
        ref_id = int(u[6])
        bonus = 20
        cur.execute("UPDATE users SET balance=balance+? WHERE id=?", (bonus, ref_id))
        cur.execute("INSERT INTO ref_purchases(user_id, ref_id, amount, created) VALUES(?,?,?,?)",
                   (c.from_user.id, ref_id, bonus, datetime.now().strftime("%d.%m.%Y %H:%M")))
        db.commit()
        try:
            bot.send_message(ref_id, f"🎉 Ваш реферал купил подписку {plan_name}!\n💰 +{bonus} кредитов на баланс!")
        except:
            pass
    
    bot.edit_message_text(f"""<b>💳 Подключение {plan_name}</b>

Для подключения обратитесь в поддержку: @SAIREXAIR

💰 При покупке через реферальную ссылку вы получите 20% на баланс!
👥 Ваш реферальный код: <code>{u[5]}</code>

⚡ После подключения вы сможете создавать работы.
🛡️ Чем выше тариф — тем быстрее обработка!""",
c.message.chat.id, c.message.message_id, reply_markup=back())

# СОЗДАНИЕ РАБОТЫ
@bot.callback_query_handler(func=lambda c: c.data == "create")
def create(c):
    if not has_subscription(c.from_user.id) and not is_admin(c.from_user.id):
        bot.answer_callback_query(c.id, "❌ Для создания работ нужна подписка!", show_alert=True)
        return
    k = types.InlineKeyboardMarkup(row_width=2)
    for n, v in [("👤 Аккаунт", "account"), ("👥 Группа", "group"), ("📢 Канал", "channel"),
                 ("🤖 Бот", "bot"), ("📨 Сообщение", "message"), ("🔗 Ссылка", "link")]:
        k.add(types.InlineKeyboardButton(n, callback_data="type_" + v))
    k.add(types.InlineKeyboardButton("◀️ Назад", callback_data="back"))
    bot.edit_message_text("<b>💥 Создание работы</b>\n\nВыберите тип цели:\n\n🛡️ <b>Совет:</b> Используйте защиту для повышения шансов!\n⚡ <b>Совет:</b> Ускоряйте работы за кредиты!",
                          c.message.chat.id, c.message.message_id, reply_markup=k)

@bot.callback_query_handler(func=lambda c: c.data.startswith("type_"))
def typ(c):
    if not has_subscription(c.from_user.id) and not is_admin(c.from_user.id):
        bot.answer_callback_query(c.id, "❌ Для создания работ нужна подписка!", show_alert=True)
        return
    t = c.data[5:]
    msg = bot.send_message(c.message.chat.id, f"<b>🎯 Новая работа</b>\n\nТип: <b>{t}</b>\n\nОтправьте username или ссылку.")
    bot.register_next_step_handler(msg, target, t)

def target(m, t):
    msg = bot.send_message(m.chat.id, "<b>📋 Причина</b>\n\n1️⃣ Спам\n2️⃣ Мошенничество\n3️⃣ Нарушение правил\n4️⃣ Другое\n\nОтправьте номер.")
    bot.register_next_step_handler(msg, make_job, t, m.text.strip())

def make_job(m, t, target):
    reason = {"1": "Спам", "2": "Мошенничество", "3": "Нарушение правил", "4": "Другое"}.get(m.text.strip(), "Другое")
    
    u = get_user(m.from_user.id)
    plan = u[3] if u[3] != "Нет" else "Basic"
    if is_admin(m.from_user.id):
        plan = "Админ"
    
    ai_chance, ai_time = ai_risk_analysis(t, target, plan)
    ai_text = ai_comment(ai_chance, plan)
    
    shield_used = False
    final_chance = ai_chance
    
    if u[10] > 0:
        shield_used = True
        reduction = random.randint(5, 25)
        final_chance = max(5, ai_chance - reduction)
        cur.execute("UPDATE users SET shield_active=shield_active-1, shield_uses=shield_uses+1 WHERE id=?", (m.from_user.id,))
        db.commit()
    
    cur.execute("""INSERT INTO jobs(user_id,target,target_type,reason,status,created,ai_chance,ai_time,shield_used,final_chance,boosted,boost_cost) 
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (m.from_user.id, target, t, reason, "В обработке", 
                 datetime.now().strftime("%d.%m.%Y %H:%M"), 
                 ai_chance, ai_time, 1 if shield_used else 0, final_chance, 0, 0))
    db.commit()
    jid = cur.lastrowid
    
    # Повышение уровня
    if u[8] < 5:
        cur.execute("UPDATE users SET level=level+1 WHERE id=? AND level<5", (m.from_user.id,))
        db.commit()
    
    # Обновляем статистику
    cur.execute("UPDATE users SET total_jobs=total_jobs+1 WHERE id=?", (m.from_user.id,))
    db.commit()
    
    # Проверяем квест
    today = datetime.now().strftime("%d.%m.%Y")
    if u[14] == today:
        quest_data = u[14]
        if "|" in quest_data:
            parts = quest_data.split("|")
            if len(parts) >= 3:
                cur.execute("UPDATE users SET quest_progress=quest_progress+1 WHERE id=?", (m.from_user.id,))
                db.commit()
    
    bars = "█" * (final_chance // 10) + "░" * (10 - final_chance // 10)
    
    shield_text = "\n🛡️ <b>Защита активирована!</b> Шанс снижен на {}%".format(ai_chance - final_chance) if shield_used else "\n❌ <b>Защита не использована</b> (купите в профиле)"
    
    boost_text = "\n⚡ <b>Ускорить работу?</b> Нажмите на кнопку ниже!"
    
    k = types.InlineKeyboardMarkup()
    k.add(types.InlineKeyboardButton("⚡ Ускорить (20💰)", callback_data=f"boost_{jid}_fast"),
          types.InlineKeyboardButton("💫 Мгновенно (50💰)", callback_data=f"boost_{jid}_instant"))
    k.add(types.InlineKeyboardButton("◀️ Назад", callback_data="back"))
    
    bot.send_message(m.chat.id, f"""<b>✅ Работа #{jid} создана</b>

🎯 Цель: <code>{target}</code>
📂 Тип: <b>{t}</b>
📋 Причина: <b>{reason}</b>
⏱ Время до сноса: <b>{ai_time}</b>
💎 Ваш тариф: <b>{plan}</b>
{shield_text}
{boost_text}

<blockquote>🤖 <b>AI-анализ риска:</b>
Шанс сноса: {bars} <b>{final_chance}%</b>
{ai_text}</blockquote>

🔄 Статус: <b>В обработке</b>""", reply_markup=k)
    
    threading.Thread(target=finish, args=(jid, m.chat.id, final_chance), daemon=True).start()

# УСКОРЕНИЕ РАБОТЫ
@bot.callback_query_handler(func=lambda c: c.data.startswith("boost_"))
def boost_job(c):
    parts = c.data.split("_")
    jid = int(parts[1])
    boost_type = parts[2]
    
    job = cur.execute("SELECT user_id,status,boosted FROM jobs WHERE id=?", (jid,)).fetchone()
    if not job:
        return bot.answer_callback_query(c.id, "❌ Работа не найдена!", show_alert=True)
    if job[1] != "В обработке":
        return bot.answer_callback_query(c.id, "❌ Работа уже завершена!", show_alert=True)
    if job[2] == 1:
        return bot.answer_callback_query(c.id, "❌ Работа уже ускорена!", show_alert=True)
    if job[0] != c.from_user.id and not is_admin(c.from_user.id):
        return bot.answer_callback_query(c.id, "❌ Это не ваша работа!", show_alert=True)
    
    cost = 20 if boost_type == "fast" else 50
    u = get_user(c.from_user.id)
    if u[2] < cost:
        return bot.answer_callback_query(c.id, f"❌ Недостаточно кредитов! Нужно {cost}", show_alert=True)
    
    cur.execute("UPDATE users SET balance=balance-? WHERE id=?", (cost, c.from_user.id))
    cur.execute("UPDATE jobs SET boosted=1, boost_cost=? WHERE id=?", (cost, jid))
    db.commit()
    
    if boost_type == "fast":
        bot.answer_callback_query(c.id, "⚡ Работа ускорена в 2 раза!", show_alert=True)
        threading.Thread(target=lambda: finish_fast(jid, c.message.chat.id), daemon=True).start()
        bot.edit_message_text(f"⚡ <b>Работа #{jid} ускорена!</b>\n⏱ Время сокращено в 2 раза!", 
                            c.message.chat.id, c.message.message_id)
    else:
        bot.answer_callback_query(c.id, "💫 Работа завершена мгновенно!", show_alert=True)
        finish_instant(jid, c.message.chat.id)
        bot.edit_message_text(f"💫 <b>Работа #{jid} завершена мгновенно!</b>", 
                            c.message.chat.id, c.message.message_id)

def finish_fast(jid, chat):
    time.sleep(3)
    job = cur.execute("SELECT final_chance FROM jobs WHERE id=?", (jid,)).fetchone()
    chance = job[0] if job else 50
    if random.randint(1, 100) < chance:
        status = "❌ Снесено"
    else:
        status = "✅ Выжило"
    
    cur.execute("UPDATE jobs SET status=?, completed=? WHERE id=?", 
                (status, datetime.now().strftime("%d.%m.%Y %H:%M"), jid))
    if status == "✅ Выжило":
        cur.execute("UPDATE users SET total_survived=total_survived+1 WHERE id=(SELECT user_id FROM jobs WHERE id=?)", (jid,))
    db.commit()
    try:
        bot.send_message(chat, f"⚡ <b>Работа #{jid} завершена (ускоренно)</b>\n\nСтатус: {status}")
    except:
        pass

def finish_instant(jid, chat):
    job = cur.execute("SELECT final_chance FROM jobs WHERE id=?", (jid,)).fetchone()
    chance = job[0] if job else 50
    if random.randint(1, 100) < chance:
        status = "❌ Снесено"
    else:
        status = "✅ Выжило"
    
    cur.execute("UPDATE jobs SET status=?, completed=? WHERE id=?", 
                (status, datetime.now().strftime("%d.%m.%Y %H:%M"), jid))
    if status == "✅ Выжило":
        cur.execute("UPDATE users SET total_survived=total_survived+1 WHERE id=(SELECT user_id FROM jobs WHERE id=?)", (jid,))
    db.commit()
    try:
        bot.send_message(chat, f"💫 <b>Работа #{jid} завершена мгновенно!</b>\n\nСтатус: {status}")
    except:
        pass

# ОБЫЧНОЕ ЗАВЕРШЕНИЕ
def finish(jid, chat, chance):
    time.sleep(6)
    if random.randint(1, 100) < chance:
        status = "❌ Снесено"
    else:
        status = "✅ Выжило"
    
    cur.execute("UPDATE jobs SET status=?, completed=? WHERE id=?", 
                (status, datetime.now().strftime("%d.%m.%Y %H:%M"), jid))
    if status == "✅ Выжило":
        cur.execute("UPDATE users SET total_survived=total_survived+1 WHERE id=(SELECT user_id FROM jobs WHERE id=?)", (jid,))
    db.commit()
    try:
        bot.send_message(chat, f"""<b>📊 Работа #{jid}</b>

██████████████ 100%

<b>✅ Обработка завершена</b>
Статус: <b>{status}</b>
🕐 Финиш: {datetime.now().strftime("%d.%m.%Y %H:%M")}""")
    except:
        pass

# МОИ РАБОТЫ
@bot.callback_query_handler(func=lambda c: c.data == "jobs")
def jobs(c):
    rows = cur.execute("""SELECT id,target,target_type,status,created,ai_chance,final_chance,shield_used,boosted 
                          FROM jobs WHERE user_id=? ORDER BY id DESC LIMIT 10""", (c.from_user.id,)).fetchall()
    text = "<b>📋 История работ</b>\n\n"
    if not rows:
        text += "У вас пока нет работ."
    else:
        for r in rows:
            emoji = "🟢" if r[3] == "✅ Выжило" else "🔴" if r[3] == "❌ Снесено" else "🟡"
            shield = "🛡️" if r[7] == 1 else " "
            boost = "⚡" if r[8] == 1 else " "
            text += f"{emoji} #{r[0]} {shield}{boost} • {r[2]}\n🎯 <code>{r[1]}</code>\n📊 {r[3]}\n🎲 Шанс: {r[6]}% (был {r[5]}%)\n🕐 {r[4]}\n\n"
    bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=back())

# РЕФЕРАЛЫ
@bot.callback_query_handler(func=lambda c: c.data == "ref")
def ref(c):
    u = get_user(c.from_user.id)
    refs = cur.execute("SELECT COUNT(*) FROM users WHERE ref_by=?", (c.from_user.id,)).fetchone()[0]
    ref_earnings = cur.execute("SELECT SUM(amount) FROM ref_purchases WHERE ref_id=?", (c.from_user.id,)).fetchone()[0] or 0
    
    text = f"""<b>👥 Реферальная система</b>

Ваш реферальный код:
<code>{u[5]}</code>

🔗 Ссылка для приглашения:
<code>https://t.me/{(bot.get_me()).username}?start={c.from_user.id}</code>

📊 Статистика:
👥 Приглашено: <b>{refs}</b>
💰 Заработано: <b>{ref_earnings} кредитов</b>

💡 <b>Как это работает:</b>
• За каждую покупку подписки вашим рефералом вы получаете <b>20%</b> на баланс
• Приглашайте друзей и зарабатывайте!"""
    
    k = types.InlineKeyboardMarkup()
    k.add(types.InlineKeyboardButton("🔗 Поделиться", callback_data="share_ref"))
    k.add(types.InlineKeyboardButton("◀️ Назад", callback_data="back"))
    bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=k)

@bot.callback_query_handler(func=lambda c: c.data == "share_ref")
def share_ref(c):
    u = get_user(c.from_user.id)
    bot.send_message(c.message.chat.id, f"🔗 Ваша реферальная ссылка:\n<code>https://t.me/{(bot.get_me()).username}?start={c.from_user.id}</code>")

# ЗАПРОСЫ
@bot.callback_query_handler(func=lambda c: c.data == "requests")
def reqs(c):
    k = types.InlineKeyboardMarkup()
    k.add(types.InlineKeyboardButton("➕ Создать запрос", callback_data="new_request"))
    k.add(types.InlineKeyboardButton("◀️ Назад", callback_data="back"))
    bot.edit_message_text("<b>📨 Мои запросы</b>\n\nЗдесь отображаются обращения.\n\nПо всем вопросам пишите: @SAIREXAIR", 
c.message.chat.id, c.message.message_id, reply_markup=k)

@bot.callback_query_handler(func=lambda c: c.data == "new_request")
def newreq(c):
    msg = bot.send_message(c.message.chat.id, "<b>📝 Новый запрос</b>\n\nОпишите запрос одним сообщением.")
    bot.register_next_step_handler(msg, savereq)

def savereq(m):
    cur.execute("INSERT INTO requests(user_id,text,status,created) VALUES(?,?,?,?)",
                (m.from_user.id, m.text, "Ожидает", datetime.now().strftime("%d.%m.%Y %H:%M")))
    db.commit()
    bot.send_message(m.chat.id, f"✅ Запрос принят. Номер: <code>REQ-{cur.lastrowid:04d}</code>", reply_markup=back())

# ПОДДЕРЖКА
@bot.callback_query_handler(func=lambda c: c.data == "support")
def support(c):
    bot.edit_message_text("""<b>🆘 Поддержка</b>

📌 По всем вопросам обращайтесь к:
👤 <b>@SAIREXAIR</b>

💡 Создайте обращение через раздел «Мои запросы».
💰 Для покупки подписки пишите в поддержку.
📖 Инструкция есть в главном меню.""",
c.message.chat.id, c.message.message_id, reply_markup=back())

# НАЗАД
@bot.callback_query_handler(func=lambda c: c.data == "back")
def backcmd(c):
    bot.edit_message_text("<b>⚡ Control Center</b>\n\nВыберите раздел:", 
c.message.chat.id, c.message.message_id, reply_markup=menu(c.from_user.id))

# АДМИН-ПАНЕЛЬ
@bot.callback_query_handler(func=lambda c: c.data == "admin")
def adm(c):
    if not is_admin(c.from_user.id):
        return
    k = types.InlineKeyboardMarkup(row_width=2)
    k.add(types.InlineKeyboardButton("🎁 Выдать подписку", callback_data="give_sub"),
          types.InlineKeyboardButton("📨 Выдать запрос", callback_data="give_req"))
    k.add(types.InlineKeyboardButton("👥 Пользователи", callback_data="users"),
          types.InlineKeyboardButton("📊 Статистика", callback_data="stats"))
    k.add(types.InlineKeyboardButton("💥 Все работы", callback_data="all_jobs"),
          types.InlineKeyboardButton("📨 Все запросы", callback_data="all_requests"))
    k.add(types.InlineKeyboardButton("💸 Выдать баланс", callback_data="give_balance"),
          types.InlineKeyboardButton("📢 Рассылка", callback_data="broadcast"))
    k.add(types.InlineKeyboardButton("◀️ Назад", callback_data="back"))
    bot.edit_message_text("<b>⚙️ Админ-панель</b>\n\n👑 Админ: @SAIREXAIR\nВыберите действие:", 
c.message.chat.id, c.message.message_id, reply_markup=k)

# ВЫДАТЬ ПОДПИСКУ
@bot.callback_query_handler(func=lambda c: c.data == "give_sub")
def givesub(c):
    if not is_admin(c.from_user.id):
        return
    msg = bot.send_message(c.message.chat.id, """Введите данные для выдачи подписки:

<code>ID ТАРИФ СРОК</code>

Примеры:
<code>123456789 Premium 30</code> — на 30 дней
<code>123456789 Standard 7</code> — на 7 дней
<code>123456789 Lifetime 0</code> — навсегда

Доступные тарифы: Basic, Standard, Premium, PRO, Lifetime""")
    bot.register_next_step_handler(msg, sub_give)

def sub_give(m):
    parts = m.text.split()
    if len(parts) < 3:
        return bot.send_message(m.chat.id, "❌ Неверный формат. Используйте: ID ТАРИФ СРОК")
    try:
        uid = int(parts[0])
        plan = parts[1]
        days = int(parts[2])
    except:
        return bot.send_message(m.chat.id, "❌ Неверные данные.")
    
    if plan not in ["Basic", "Standard", "Premium", "PRO", "Lifetime"]:
        return bot.send_message(m.chat.id, "❌ Неверный тариф.")
    
    if plan == "Lifetime" or days == 0:
        exp = "Навсегда"
    else:
        exp = (datetime.now() + timedelta(days=days)).strftime("%d.%m.%Y")
    
    cur.execute("UPDATE users SET plan=?, expires=? WHERE id=?", (plan, exp, uid))
    db.commit()
    bot.send_message(m.chat.id, f"✅ Подписка выдана\n\nID: <code>{uid}</code>\nТариф: <b>{plan}</b>\nДо: <b>{exp}</b>")
    try:
        bot.send_message(uid, f"<b>🎉 Вам выдана подписка!</b>\n\nТариф: <b>{plan}</b>\nДо: <b>{exp}</b>\n\nТеперь вы можете создавать работы.")
    except:
        pass

# ВЫДАТЬ БАЛАНС
@bot.callback_query_handler(func=lambda c: c.data == "give_balance")
def give_balance(c):
    if not is_admin(c.from_user.id):
        return
    msg = bot.send_message(c.message.chat.id, "Введите: <code>ID СУММА</code>\n\nПример: <code>123456789 100</code>")
    bot.register_next_step_handler(msg, balance_give)

def balance_give(m):
    parts = m.text.split()
    if len(parts) < 2:
        return bot.send_message(m.chat.id, "❌ Неверный формат.")
    try:
        uid = int(parts[0])
        amount = int(parts[1])
    except:
        return bot.send_message(m.chat.id, "❌ Неверные данные.")
    
    cur.execute("UPDATE users SET balance=balance+? WHERE id=?", (amount, uid))
    db.commit()
    bot.send_message(m.chat.id, f"✅ Баланс пополнен на {amount} кредитов для ID {uid}")
    try:
        bot.send_message(uid, f"💰 Ваш баланс пополнен на <b>{amount}</b> кредитов!")
    except:
        pass

# РАССЫЛКА
@bot.callback_query_handler(func=lambda c: c.data == "broadcast")
def broadcast(c):
    if not is_admin(c.from_user.id):
        return
    msg = bot.send_message(c.message.chat.id, "📢 Введите текст для рассылки:")
    bot.register_next_step_handler(msg, send_broadcast)

def send_broadcast(m):
    users = cur.execute("SELECT id FROM users").fetchall()
    success = 0
    for u in users:
        try:
            bot.send_message(u[0], f"📢 <b>Объявление</b>\n\n{m.text}")
            success += 1
            time.sleep(0.1)
        except:
            pass
    bot.send_message(m.chat.id, f"✅ Рассылка отправлена {success} пользователям!")

# ВЫДАТЬ ЗАПРОС
@bot.callback_query_handler(func=lambda c: c.data == "give_req")
def givereq(c):
    if not is_admin(c.from_user.id):
        return
    msg = bot.send_message(c.message.chat.id, "Введите Telegram ID пользователя:")
    bot.register_next_step_handler(msg, reqid)

def reqid(m):
    try:
        uid = int(m.text)
    except:
        return bot.send_message(m.chat.id, "❌ Неверный ID.")
    msg = bot.send_message(m.chat.id, "Введите текст задания:")
    bot.register_next_step_handler(msg, reqtext, uid)

def reqtext(m, uid):
    cur.execute("INSERT INTO requests(user_id,text,status,created) VALUES(?,?,?,?)",
                (uid, m.text, "Назначен", datetime.now().strftime("%d.%m.%Y %H:%M")))
    db.commit()
    rid = cur.lastrowid
    bot.send_message(m.chat.id, f"✅ Запрос <b>#{rid}</b> назначен.")
    try:
        bot.send_message(uid, f"<b>📨 Вам назначен новый запрос</b>\n\nНомер: <code>REQ-{rid:04d}</code>\n\n📝 {m.text}")
    except:
        pass

# СТАТИСТИКА
@bot.callback_query_handler(func=lambda c: c.data == "stats")
def stats(c):
    if not is_admin(c.from_user.id):
        return
    u = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    j = cur.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    r = cur.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
    sub = cur.execute("SELECT COUNT(*) FROM users WHERE plan != 'Нет'").fetchone()[0]
    ref = cur.execute("SELECT SUM(ref_count) FROM users").fetchone()[0] or 0
    survived = cur.execute("SELECT COUNT(*) FROM jobs WHERE status='✅ Выжило'").fetchone()[0]
    deleted = cur.execute("SELECT COUNT(*) FROM jobs WHERE status='❌ Снесено'").fetchone()[0]
    boosted = cur.execute("SELECT COUNT(*) FROM jobs WHERE boosted=1").fetchone()[0]
    
    bot.edit_message_text(f"""<b>📊 Статистика</b>

👥 Пользователей: <b>{u}</b>
💥 Работ: <b>{j}</b>
📨 Запросов: <b>{r}</b>
💎 С подпиской: <b>{sub}</b>
👥 Рефералов всего: <b>{ref}</b>
✅ Выжило: <b>{survived}</b>
❌ Снесено: <b>{deleted}</b>
⚡ Ускорено работ: <b>{boosted}</b>
🎯 Выживаемость: <b>{round((survived/j*100) if j > 0 else 0)}%</b>""",
c.message.chat.id, c.message.message_id, reply_markup=back())

# ПОЛЬЗОВАТЕЛИ
@bot.callback_query_handler(func=lambda c: c.data == "users")
def users(c):
    if not is_admin(c.from_user.id):
        return
    rows = cur.execute("SELECT id,username,plan,expires,balance,level,total_jobs FROM users ORDER BY id DESC LIMIT 15").fetchall()
    text = "<b>👥 Последние пользователи</b>\n\n"
    for x in rows:
        status = "✅" if x[2] != "Нет" else "❌"
        level_emoji = "🌱" if x[5] == 1 else "🌿" if x[5] == 2 else "🌳" if x[5] == 3 else "🌟" if x[5] == 4 else "👑"
        text += f"<code>{x[0]}</code> @{x[1] or '-'} | {level_emoji} | {x[4]}💰 | {x[2]} {status} | {x[6]} работ\n"
    bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=back())

# ВСЕ РАБОТЫ
@bot.callback_query_handler(func=lambda c: c.data == "all_jobs")
def all_jobs(c):
    if not is_admin(c.from_user.id):
        return
    rows = cur.execute("SELECT id,user_id,target,target_type,status,ai_chance,boosted FROM jobs ORDER BY id DESC LIMIT 20").fetchall()
    text = "<b>💥 Все работы (последние 20)</b>\n\n"
    if not rows:
        text += "Работ нет."
    else:
        for r in rows:
            emoji = "🟢" if r[4] == "✅ Выжило" else "🔴" if r[4] == "❌ Снесено" else "🟡"
            boost = "⚡" if r[6] == 1 else " "
            text += f"{emoji} #{r[0]} {boost}| <code>{r[1]}</code> | {r[2][:20]} | {r[3]} | {r[4]} | {r[5]}%\n"
    bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=back())

# ВСЕ ЗАПРОСЫ
@bot.callback_query_handler(func=lambda c: c.data == "all_requests")
def all_requests(c):
    if not is_admin(c.from_user.id):
        return
    rows = cur.execute("SELECT id,user_id,text,status FROM requests ORDER BY id DESC LIMIT 20").fetchall()
    text = "<b>📨 Все запросы (последние 20)</b>\n\n"
    if not rows:
        text += "Запросов нет."
    else:
        for r in rows:
            text += f"REQ-{r[0]:04d} | <code>{r[1]}</code> | {r[2][:30]} | {r[3]}\n"
    bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=back())

# ЗАПУСК
print("🤖 Bot started by @SAIREXAIR")
print("📊 Все функции активны!")
print("🎁 Кейсы, квесты, достижения, ускорение, автопродление!")

while True:
    try:
        bot.infinity_polling(timeout=30, long_polling_timeout=30)
    except Exception as e:
        print(e)
        time.sleep(5)