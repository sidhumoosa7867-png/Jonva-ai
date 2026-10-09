import os
import re
import sqlite3
import asyncio
import edge_tts
import requests
from io import BytesIO
from flask import Flask, request, jsonify, send_from_directory, send_file, session
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__, static_folder='.')
app.secret_key = "jonva_ai_secure_session_key_2026"

# 🔑 आपकी 100% काम करने वाली असली Groq Key
GROQ_API_KEY = "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"

# 👑 एडमिन ईमेल (यहाँ अपना असली ईमेल रखें)
ADMIN_EMAIL = "sidhumoosa7867@gmail.com"

# ----------------- 1. डेटाबेस (यूज़र्स और लॉगिन) -----------------
def get_db():
    conn = sqlite3.connect('jonva.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT,
                google_id TEXT,
                role TEXT DEFAULT 'user',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()

init_db()

# ----------------- 2. AI और मेमोरी (Context) -----------------
conversation_history = [
    {
        "role": "system",
        "content": "तुम 'jonva AI' हो—एक अत्यंत समझदार और दोस्ताना AI साथी। यूज़र जिस भी भाषा में पूछे (हिंदी, पंजाबी, इंग्लिश आदि), उसी भाषा में 2 से 3 वाक्यों में सीधा, सटीक और स्वाभाविक जवाब दो। पिछली बातचीत के संदर्भ को हमेशा याद रखो।"
    }
]

def ask_ai(prompt):
    global conversation_history
    conversation_history.append({"role": "user", "content": prompt})

    # सिर्फ़ पिछली 10 बातें याद रखें ताकि स्पीड तेज़ रहे
    if len(conversation_history) > 11:
        conversation_history = [conversation_history[0]] + conversation_history[-10:]

    if GROQ_API_KEY:
        try:
            groq_url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            }
            body = {
                "model": "openai/gpt-oss-20b",
                "messages": conversation_history
            }
            res = requests.post(groq_url, headers=headers, json=body, timeout=25)
            data = res.json()
            if "choices" in data and data["choices"]:
                reply = data["choices"][0]["message"]["content"].strip()
                conversation_history.append({"role": "assistant", "content": reply})
                return reply
            else:
                print("[Groq Error Detail]:", data)
        except Exception as e:
            print("[Groq Connection Error]:", e)

    return "सर, अभी AI सर्वर से जवाब नहीं मिल पा रहा है।"

# ----------------- 3. आवाज़ इंजन (TTS) -----------------
def get_neural_voice(text):
    if re.search(r'[\u0A00-\u0A7F]', text):
        return "pa-IN-VaaniNeural"
    elif re.search(r'[\u0900-\u097F]', text):
        return "hi-IN-SwaraNeural"
    return "en-IN-NeerjaNeural"

# ----------------- 4. API एंडपॉइंट्स -----------------
@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.get_json() or {}
    user_prompt = data.get('prompt', '').strip()
    if not user_prompt:
        return jsonify({"error": "खाली सवाल"}), 400
    reply = ask_ai(user_prompt)
    return jsonify({"reply": reply})

@app.route('/api/tts', methods=['POST'])
def tts():
    data = request.get_json() or {}
    text = data.get('text', '').strip()
    if not text:
        return jsonify({"error": "खाली टेक्स्ट"}), 400
    voice = get_neural_voice(text)
    try:
        communicate = edge_tts.Communicate(text, voice)
        stream = BytesIO()
        async def run_tts():
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    stream.write(chunk["data"])
        asyncio.run(run_tts())
        stream.seek(0)
        return send_file(stream, mimetype="audio/mpeg")
    except Exception as e:
        print("[TTS Error]:", e)
        return jsonify({"error": str(e)}), 500

# ----------------- 5. लॉगिन / साइन-अप रूट्स -----------------
@app.route('/api/auth/signup', methods=['POST'])
def signup():
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not name or not email or not password:
        return jsonify({"error": "सभी फ़ील्ड भरें।"}), 400

    hashed_pw = generate_password_hash(password)
    role = 'admin' if email == ADMIN_EMAIL else 'user'

    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO users (name, email, password, role) VALUES (?, ?, ?, ?)",
                        (name, email, hashed_pw, role))
            conn.commit()
            user_id = cur.lastrowid

        session['user_id'] = user_id
        session['user_role'] = role
        return jsonify({"message": "अकाउंट बन गया!", "user": {"name": name, "email": email, "role": role}})
    except sqlite3.IntegrityError:
        return jsonify({"error": "यह ईमेल पहले से मौजूद है।"}), 400

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

    if user and user['password'] and check_password_hash(user['password'], password):
        session['user_id'] = user['id']
        session['user_role'] = user['role']
        return jsonify({"message": "लॉगिन सफल!", "user": {"name": user['name'], "email": user['email'], "role": user['role']}})
    
    return jsonify({"error": "गलत ईमेल या पासवर्ड।"}), 401

@app.route('/api/auth/google', methods=['POST'])
def google_auth():
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    name = data.get('name', '').strip()
    google_id = data.get('sub', '')

    if not email:
        return jsonify({"error": "अमान्य Google डेटा"}), 400

    role = 'admin' if email == ADMIN_EMAIL else 'user'

    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not user:
            cur = conn.cursor()
            cur.execute("INSERT INTO users (name, email, google_id, role) VALUES (?, ?, ?, ?)",
                        (name, email, google_id, role))
            conn.commit()
            user_id = cur.lastrowid
        else:
            user_id = user['id']
            role = user['role']

    session['user_id'] = user_id
    session['user_role'] = role
    return jsonify({"message": "Google लॉगिन सफल!", "user": {"name": name, "email": email, "role": role}})

@app.route('/api/auth/me', methods=['GET'])
def get_me():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"user": None})
    with get_db() as conn:
        user = conn.execute("SELECT id, name, email, role FROM users WHERE id = ?", (user_id,)).fetchone()
    return jsonify({"user": dict(user) if user else None})

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"message": "लॉगआउट हो गया"})

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def static_files(path):
    return send_from_directory('.', path)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8000))
    app.run(host='0.0.0.0', port=port)
