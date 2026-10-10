import os
import time
import glob
import asyncio
from flask import Flask, request, jsonify, send_file, send_from_directory
import requests
import edge_tts

app = Flask(__name__, static_folder='.', static_url_path='')

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.1-8b-instant"

AUDIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

def cleanup_old_audio():
    try:
        now = time.time()
        for f in glob.glob(os.path.join(AUDIO_DIR, "*.mp3")):
            if os.stat(f).st_mtime < now - 600:
                os.remove(f)
    except Exception as e:
        app.logger.warning(f"Audio cleanup notice: {e}")

@app.route("/")
def home():
    return send_from_directory(".", "index.html")

@app.route("/chat", methods=["POST"])
@app.route("/api/chat", methods=["POST"])
def chat():
    if not request.is_json:
        return jsonify({"error": "JSON format required."}), 400

    data = request.get_json()
    user_message = data.get("message") or data.get("prompt") or ""
    user_message = str(user_message).strip()

    if not user_message:
        return jsonify({"error": "Message cannot be empty."}), 400

    if len(user_message) > 4000:
        return jsonify({"error": "Message is too long."}), 400

    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return jsonify({"error": "Groq API Key is not set in Render environment."}), 500

    system_prompt = (
        "You are JONVA AI, a polite, smart, and helpful AI assistant. "
        "Reply naturally in Hindi, English, or Hinglish depending on what the user asks. "
        "Keep answers clear, well-formatted, and helpful."
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "temperature": 0.7,
        "max_tokens": 1024
    }

    try:
        response = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=25)
        if response.status_code != 200:
            err = response.json().get("error", {}).get("message", "API error")
            return jsonify({"error": f"AI error: {err}"}), response.status_code

        res_data = response.json()
        ai_reply = res_data["choices"][0]["message"]["content"]

        return jsonify({
            "reply": ai_reply,
            "response": ai_reply,
            "status": "success"
        })
    except requests.exceptions.Timeout:
        return jsonify({"error": "Request timed out. Please try again."}), 504
    except Exception as e:
        return jsonify({"error": f"Server error: {str(e)}"}), 500

@app.route("/tts", methods=["POST"])
@app.route("/api/tts", methods=["POST"])
def tts():
    if not request.is_json:
        return jsonify({"error": "JSON required."}), 400

    data = request.get_json()
    text = data.get("text", "").strip()
    voice = data.get("voice", "hi-IN-SwaraNeural")

    if not text:
        return jsonify({"error": "No text provided."}), 400

    if len(text) > 1000:
        text = text[:1000]

    cleanup_old_audio()
    filename = f"speech_{int(time.time()*1000)}.mp3"
    filepath = os.path.join(AUDIO_DIR, filename)

    async def generate_speech():
        comm = edge_tts.Communicate(text, voice)
        await comm.save(filepath)

    try:
        asyncio.run(generate_speech())
        if os.path.exists(filepath):
            return send_file(filepath, mimetype="audio/mpeg")
        return jsonify({"error": "Could not generate audio."}), 500
    except Exception as e:
        return jsonify({"error": f"TTS error: {str(e)}"}), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "JONVA AI",
        "api_configured": bool(os.getenv("GROQ_API_KEY"))
    }), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
