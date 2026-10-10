import os
import time
import glob
import asyncio
import urllib.parse
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

# Real AI Image Generation Route (State-of-the-Art Flux Engine)
@app.route("/generate-image", methods=["POST"])
@app.route("/api/generate-image", methods=["POST"])
def generate_image():
    if not request.is_json:
        return jsonify({"error": "JSON format required"}), 400
    
    data = request.get_json()
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "Prompt cannot be empty"}), 400

    encoded_prompt = urllib.parse.quote(prompt)
    seed = int(time.time() * 1000) % 999999
    # Ultra-realistic Flux model image endpoint
    image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&model=flux&nologo=true&seed={seed}"
    
    return jsonify({
        "status": "success",
        "image_url": image_url,
        "prompt": prompt
    })

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

    # Auto-detect image generation requests
    lower_msg = user_message.lower()
    img_triggers = ["generate image", "image of", "photo of", "picture of", "photo banao", "image banao", "tasveer", "draw "]
    if any(trigger in lower_msg for trigger in img_triggers):
        clean_prompt = user_message
        for t in ["generate an image of", "generate image of", "create an image of", "photo banao", "image banao"]:
            clean_prompt = clean_prompt.replace(t, "")
        clean_prompt = clean_prompt.strip() or user_message
        encoded_prompt = urllib.parse.quote(clean_prompt)
        seed = int(time.time() * 1000) % 999999
        img_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&model=flux&nologo=true&seed={seed}"
        return jsonify({
            "reply": f"Maine aapki request ke anusaar image create kar di hai: '{clean_prompt}'",
            "image_url": img_url,
            "status": "success"
        })

    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return jsonify({"error": "Groq API Key is missing in Render environment."}), 500

    system_prompt = (
        "You are JONVA AI, a futuristic and highly intelligent AI assistant created by Gulfam. "
        "You help users with AI tools, coding, creative ideas, homework, and technology. "
        "Reply naturally in Hindi, English, or Hinglish with clean formatting, bullet points, and friendly emojis."
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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
