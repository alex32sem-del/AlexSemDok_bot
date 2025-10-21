import telegram
from telegram import Update, ForceReply
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
import random
import os
import io
import zipfile
import asyncio

# Библиотеки для PDF и изображений
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.lib.colors import black
from PIL import Image, ImageDraw, ImageFont
from faker import Faker

# Библиотека Google GenAI для генерации изображений
from google import genai
from google.genai.errors import APIError

# --- КОНФИГУРАЦИЯ ---
PASSWORD = "1232580Alex+"
AUTHORIZED_USERS = {} # {chat_id: True}
# --------------------

# Инициализация клиента Gemini (будет использоваться асинхронно)
GEMINI_CLIENT = None

# --- ДАННЫЕ ИЗ DOCGEN.HTML (с исправлениями) ---
brazilianUniversities = [
    "Technische Universität Berlin (TU Berlin)",
    "Humboldt-Universität zu Berlin (HU Berlin)",
    "Freie Universität Berlin (FU Berlin)",
    "Universität der Künste Berlin (UdK Berlin)",
    "Berlin International University of Applied Sciences (BI Berlin)",
    "International Psychoanalytic University Berlin (IPU Berlin)",
    "Sigmund Freud Privatuniversität Berlin (SFU Berlin)",
    "Europäisches Theaterinstitut Berlin (ETI Berlin)",
    "Alfred Adler Institut Berlin (AAI Berlin)",
    "Institut für Angewandte Gerontologie (IAG)",
    "Berliner Lehr- Und Forschungsinstitut (BLFI)",
    "Charité – Universitätsmedizin Berlin (Charité)"
]
firstNames = ["Max", "Paul", "Leon", "Jonas", "Elias", "Finn", "Luis", "Tim", "Felix", "Noah", "Moritz", "Lukas", "Julian", "Jan", "Fabian", "Philipp", "David", "Tom", "Simon", "Ben", "Florian", "Erik", "Nico", "Johannes"]
femaleFirstNames = ["Anna", "Lea", "Emma", "Mia", "Sofia", "Lisa", "Luisa", "Hannah", "Marie", "Laura", "Julia", "Lena", "Sara", "Clara", "Vanessa", "Katharina", "Johanna", "Amelie", "Paula", "Franziska", "Melina", "Isabelle", "Greta", "Charlotte"]
lastNames = ["Müller", "Schmidt", "Schneider", "Fischer", "Weber", "Meyer", "Wagner", "Becker", "Schulz", "Hoffmann", "Schäfer", "Koch", "Bauer", "Richter", "Klein", "Wolf", "Neumann", "Schwarz", "Zimmermann", "Braun", "Krüger", "Hofmann", "Hartmann", "Lange"]
programs = ["Informatik", "Medizin", "Rechtswissenschaft", "Architektur", "Betriebswirtschaftslehre", "Psychologie", "Volkswirtschaftslehre", "Kommunikationswissenschaft", "Bauingenieurwesen", "Biomedizin"]
courses = [
    {'code': 'INF-101', 'name': 'Mathematik', 'location': 'Raum 101'},
    {'code': 'INF-102', 'name': 'Programmierung', 'location': 'Informatiklabor'},
    {'code': 'PHY-101', 'name': 'Klassische Physik', 'location': 'Raum 203'},
    {'code': 'LAW-201', 'name': 'Verfassungsrecht', 'location': 'Raum 105'},
    {'code': 'MED-301', 'name': 'Humananatomie', 'location': 'Hörsaal'},
    {'code': 'BWL-202', 'name': 'Finanzbuchhaltung', 'location': 'Raum 302'},
    {'code': 'ARC-103', 'name': 'Architekturzeichnen', 'location': 'Atelier I'},
    {'code': 'PSY-204', 'name': 'Entwicklungspsychologie', 'location': 'Raum 207'}
]
deptCodes = ["INF", "LAW", "MED", "PHY", "BWL", "ARC", "VWL", "KOM"]
fake = Faker('de_DE') 

def generate_student_data():
    # ... (логика генерации данных студента остается прежней)
    is_male = random.choice([True, False])
    student_first_name = random.choice(firstNames if is_male else femaleFirstNames)
    student_last_name = random.choice(lastNames)
    university = random.choice(brazilianUniversities)
    program = random.choice(programs)
    current_year = 2025 
    enrollment_no = f"{random.choice(deptCodes)}-{random.randint(1000, 9999)}-{current_year}"
    birth_year = random.randint(current_year - 23, current_year - 18)
    birth_month = random.randint(1, 12)
    birth_day = random.randint(1, 28)
    dob = f"{birth_day:02d}/{birth_month:02d}/{birth_year}"
    email = f"{student_first_name.lower().replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue')}{student_last_name.lower().replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue')}{birth_year}@gmail.com"
    email = ''.join(c for c in email if c.isalnum() or c in ('.', '@'))
    valid_thru = f"{random.randint(1, 12):02d}/{current_year + 4}"
    today = fake.date_of_birth(minimum_age=0, maximum_age=0).strftime("%d/%m/%Y")
    semester = "Semestre 2025-2026"
    random_amount = random.randint(800, 2000)
    selected_courses = random.sample(courses, 4)

    return {
        'university': university,
        'name': f"{student_first_name} {student_last_name}",
        'enrollment_no': enrollment_no,
        'program': program,
        'dob': dob,
        'valid_thru': valid_thru,
        'email': email,
        'today': today,
        'semester': semester,
        'amount': f"€{random_amount:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'),
        'raw_amount': random_amount,
        'courses': selected_courses
    }

# --- ИНТЕГРАЦИЯ GEMINI API ---

def _create_error_image_reader(text, size=(100, 100), is_signature=False):
    """Fallback: Создает заглушку-изображение."""
    img = Image.new('RGB', size, color='white')
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 10 if is_signature else 20)
    except IOError:
        font = ImageFont.load_default() 
    
    text_color = 'red' if 'ERROR' in text else 'gray'
    if is_signature:
        text_pos = (10, 50) 
        d.text(text_pos, text, fill=text_color, font=font)
    else:
        text_w, text_h = d.textsize(text, font)
        text_pos = ((size[0] - text_w) / 2, (size[1] - text_h) / 2)
        d.text(text_pos, text, fill=text_color, font=font)
        
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    return ImageReader(img_byte_arr)

async def generate_image_reader(prompt: str, is_signature: bool = False):
    """Генерирует изображение с помощью Gemini API и возвращает ImageReader."""
    global GEMINI_CLIENT
    if GEMINI_CLIENT is None:
         # Инициализация клиента, если он еще не инициализирован
        try:
            GEMINI_CLIENT = genai.Client()
        except Exception as e:
            print(f"Error initializing Gemini client: {e}")
            return _create_error_image_reader("API KEY ERROR", size=(100, 100))

    aspect_ratio = "1:1" if not is_signature else "3:1"
    
    try:
        # Асинхронный вызов API
        result = await GEMINI_CLIENT.models.generate_images_async(
            model='imagen-3.0-generate-002',
            prompt=prompt,
            config=dict(
                number_of_images=1,
                output_mime_type="image/png",
                aspect_ratio=aspect_ratio 
            )
        )
        
        if result.generated_images:
            image_data = result.generated_images[0].image.image_bytes
            return ImageReader(io.BytesIO(image_data))
            
    except APIError as e:
        print(f"Gemini API Error: {e}")
        return _create_error_image_reader("GEMINI API ERROR", size=(100, 100))
    except Exception as e:
        print(f"General Image Generation Error: {e}")
        return _create_error_image_reader("GENERATION ERROR", size=(100, 100))

# --- ГЕНЕРАЦИЯ PDF (с ImageReader) ---

def create_id_card_pdf(data, photo_reader):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(280, 180)) 
    
    c.setFont('Helvetica-Bold', 12)
    c.drawString(10, 160, 'IDENTITÄTSKARTE')
    
    # Логотип (простая заглушка, так как API использовался только для фото/подписи)
    c.setFont('Helvetica-Bold', 8)
    c.drawString(30, 148, data['university'])

    # ФОТО (Используем сгенерированное ImageReader)
    c.drawImage(photo_reader, 15, 45, width=40, height=50)

    # Детали
    c.setFont('Helvetica-Bold', 6)
    c.drawString(70, 100, f"REGISTRIERUNG NR: {data['enrollment_no']}")
    c.setFont('Helvetica-Bold', 10)
    c.drawString(70, 85, f"NAME: {data['name'].upper()}")
    c.setFont('Helvetica-Bold', 6)
    c.drawString(70, 70, f"KURS: {data['program'].upper()}")
    c.drawString(70, 55, f"GEBURTSDATUM: {data['dob']}")
    c.drawString(150, 55, f"GÜLTIG BIS: {data['valid_thru']}")

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer

def create_fee_receipt_pdf(data, signature_reader):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # Заголовок
    c.setFont('Helvetica-Bold', 20)
    c.drawCentredString(width / 2, height - 72, data['university'])
    c.setFont('Helvetica', 12)
    c.drawCentredString(width / 2, height - 90, 'ZAHLUNGSBELEG')

    # ... (промежуточные детали)
    y = height - 120
    c.setFont('Helvetica-Bold', 10)
    c.drawString(72, y, f"Datum: {data['today']}")
    c.drawString(width / 2, y, f"Name des Studierenden: {data['name']}")
    c.drawString(72, y - 15, f"Registrierungsnummer: {data['enrollment_no']}")
    c.drawString(width / 2, y - 15, f"Kurs: {data['program']}")
    
    y -= 60 # Позиция таблицы
    c.setFont('Helvetica-Bold', 10)
    c.line(72, y, width - 72, y)
    c.drawString(72, y - 15, "Posten")
    c.drawRightString(width - 72, y - 15, "Betrag (€)")
    c.line(72, y - 20, width - 72, y - 20)
    
    c.setFont('Helvetica', 10)
    c.drawString(72, y - 40, "Studiengebühren und weitere Kosten")
    c.drawRightString(width - 72, y - 40, data['amount'])
    
    # Итог
    c.line(72, y - 60, width - 72, y - 60)
    c.setFont('Helvetica-Bold', 10)
    c.drawString(72, y - 75, "Gesamtbetrag bezahlt:")
    c.drawRightString(width - 72, y - 75, data['amount'])

    # ПОДПИСЬ (Используем сгенерированное ImageReader)
    y -= 100
    c.drawImage(signature_reader, width - 272, y - 60, width=120, height=40)
    c.drawString(width - 250, y - 75, "____________________")
    c.drawString(width - 245, y - 90, "Autorisierte Unterschrift")
    
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer

def create_class_schedule_pdf(data, signature_reader):
    # Логика повторяет fee receipt, но использует сгенерированную подпись
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # Заголовок
    c.setFont('Helvetica-Bold', 16)
    c.drawCentredString(width / 2, height - 72, data['university'])
    c.setFont('Helvetica-Bold', 12)
    c.drawCentredString(width / 2, height - 90, 'STUNDENPLAN')

    # Детали студента
    c.setFont('Helvetica', 10)
    y = height - 130
    c.drawString(72, y, f"Name des Studierenden: {data['name']}")
    c.drawString(72, y - 15, f"Registrierungsnummer: {data['enrollment_no']}")
    c.drawString(72, y - 30, f"Semester: {data['semester']}")
    c.drawString(72, y - 45, f"Datum der Ausgabe: {data['today']}")
    
    # Таблица расписания
    y -= 70
    c.setFont('Helvetica-Bold', 10)
    c.line(72, y, width - 72, y)
    c.drawString(75, y - 15, "MODULCODE")
    c.drawString(180, y - 15, "MODULNAME")
    c.drawString(350, y - 15, "RAUM")
    c.line(72, y - 20, width - 72, y - 20)

    y -= 35
    c.setFont('Helvetica', 10)
    for course in data['courses']:
        c.drawString(75, y, course['code'])
        c.drawString(180, y, course['name'])
        c.drawString(350, y, course['location'])
        y -= 25

    # ПОДПИСЬ
    c.drawImage(signature_reader, width - 272, y - 50, width=120, height=40)
    c.drawString(width - 250, y - 65, "____________________")
    c.drawString(width - 245, y - 80, "Autorisierte Unterschrift")

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer

# --- КОМАНДЫ БОТА ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет сообщение при команде /start."""
    await update.message.reply_text(
        'Добро пожаловать в Генератор университетских документов! 👋\n\n'
        'Для начала работы вам нужно ввести пароль.\n'
        'Пожалуйста, используйте команду /auth <ваш_пароль>.'
    )

async def auth_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Проверяет пароль пользователя."""
    chat_id = update.message.chat_id
    if not context.args:
        await update.message.reply_text("Пожалуйста, введите пароль после команды /auth. Пример: /auth 12345")
        return

    user_password = context.args[0]
    if user_password == PASSWORD:
        AUTHORIZED_USERS[chat_id] = True
        await update.message.reply_text("✅ Пароль верный! Вы успешно авторизованы.\n"
                                        "Используйте команду /generate, чтобы получить ZIP-архив с документами.")
    else:
        await update.message.reply_text("❌ Неверный пароль. Попробуйте снова.")

async def generate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Генерирует документы с фото/подписью от Gemini API и отправляет ZIP-файл."""
    chat_id = update.message.chat_id
    
    if chat_id not in AUTHORIZED_USERS:
        await update.message.reply_text("Пожалуйста, сначала авторизуйтесь с помощью команды /auth <пароль>.")
        return

    message = await update.message.reply_text("⌛ Начинаю генерацию данных и изображений (Gemini API). Это займет 5-15 секунд...")
    
    try:
        data = generate_student_data()
        
        # Запросы к Gemini API для генерации изображений
        photo_prompt = f"A professional 3/4 view passport photo of a young student named {data['name']}, male or female, with a plain background, realistic photo style."
        signature_prompt = f"A realistic handwritten signature of a young student named {data['name']}, in black ink on a white background, signature style."
        
        # Асинхронное выполнение двух запросов одновременно для скорости
        photo_task = generate_image_reader(photo_prompt)
        signature_task = generate_image_reader(signature_prompt, is_signature=True)
        
        photo_reader, signature_reader = await asyncio.gather(photo_task, signature_task)
        
        # 1. Генерация PDF-файлов с использованием сгенерированных ImageReader
        id_card_pdf = create_id_card_pdf(data, photo_reader)
        fee_receipt_pdf = create_fee_receipt_pdf(data, signature_reader)
        schedule_pdf = create_class_schedule_pdf(data, signature_reader)

        # 2. Создание текстового файла
        txt_content = (
f"""NAME DER UNIVERSITÄT: {data['university']}
NAME DES SCHÜLERS: {data['name']}
E-Mail: {data['email']}
REGISTRIERUNG NR: {data['enrollment_no']}
KURS: {data['program']}
GÜLTIG BIS: {data['today']}
""")
        txt_file = io.BytesIO(txt_content.encode('utf-8'))
        
        # 3. Упаковка в ZIP-архив
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('cartao_identificacao.pdf', id_card_pdf.getvalue())
            zf.writestr('recibo_propinas.pdf', fee_receipt_pdf.getvalue())
            zf.writestr('horario_aulas.pdf', schedule_pdf.getvalue())
            zf.writestr('info.txt', txt_file.getvalue())

        zip_buffer.seek(0)

        # 4. Отправка ZIP-архива
        await context.bot.send_document(
            chat_id=chat_id,
            document=zip_buffer,
            filename='documentos_universitarios.zip',
            caption="✅ Ваши документы успешно сгенерированы и упакованы в ZIP-архив!"
        )
        await context.bot.delete_message(chat_id=chat_id, message_id=message.message_id)
    
    except Exception as e:
        print(f"Ошибка при генерации/отправке: {e}")
        await context.bot.edit_message_text(
            chat_id=chat_id, 
            message_id=message.message_id, 
            text=f"❌ Произошла ошибка при генерации документов: {e}"
        )

async def unknown_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ответ на любые другие текстовые сообщения."""
    await update.message.reply_text(
        "Я понимаю только команды. Используйте:\n"
        "1. /start для приветствия\n"
        "2. /auth 1232580Alex+ для авторизации\n"
        "3. /generate для получения документов (после авторизации)"
    )

async def post_init(application: Application) -> None:
    """Инициализация Gemini клиента после запуска приложения."""
    global GEMINI_CLIENT
    try:
        # Ключ будет автоматически взят из переменной окружения GEMINI_API_KEY
        GEMINI_CLIENT = genai.Client()
        print("Gemini client initialized successfully.")
    except Exception as e:
        print(f"Failed to initialize Gemini client: {e}. Image generation will fail. Error: {e}")

def main() -> None:
    """Запуск бота."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        print("FATAL: Переменная окружения 'TELEGRAM_BOT_TOKEN' не найдена.")
        return

    application = Application.builder().token(bot_token).post_init(post_init).build()

    # Обработчики команд
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("auth", auth_command))
    application.add_handler(CommandHandler("generate", generate_command))

    # Обработчик для всех других сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_messages))

    print("Бот запущен. Ожидание команд.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
