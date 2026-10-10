import os
import time
import glob
import asyncio
import urllib.parse
from flask import Flask, request, jsonify, send_file, send_from_directory
import requests
import edge_tts

app = Flask(__name__, static_folder='.', static_url_path='')

AUDIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

cached_groq_model = None
last_model_check = 0

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

def get_active_groq_model(api_key):
    global cached_groq_model, last_model_check
    now = time.time()
    if cached_groq_model and (now - last_model_check < 3600):
        return cached_groq_model

    try:
        res = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=8
        )
        if res.status_code == 200:
            data = res.json().get("data", [])
            valid_ids = [
                m["id"] for m in data 
                if not any(x in m["id"] for x in ["whisper", "guard", "orpheus", "safeguard", "vision"])
            ]
            
            # Priority preference for modern fast chat models
            for preferred in [
                "openai/gpt-oss-20b",
                "openai/gpt-oss-120b",
                "meta-llama/llama-4-scout-17b-16e-instruct",
                "llama-3.3-70b-versatile"
            ]:
                if preferred in valid_ids:
                    cached_groq_model = preferred
                    last_model_check = now
                    return preferred
            
            if valid_ids:
                cached_groq_model = valid_ids[0]
                last_model_check = now
                return cached_groq_model
    except Exception as e:
        app.logger.warning(f"Failed to fetch live models: {e}")

    # Fallback to current production default
    return "openai/gpt-oss-20b"

def optimize_image_prompt(raw_prompt):
    clean = raw_prompt.strip()
    for filler in [
        "generate an image of", "generate image of", "create an image of",
        "photo banao", "image banao", "photo of", "image of", "tasveer banao"
    ]:
        clean = clean.replace(filler, "")
    clean = clean.strip() or raw_prompt
    return f"{clean}, sharp facial features, detailed face, photorealistic, 8k resolution, cinematic lighting, ultra high definition"

# Real AI Image Generator (Flux Engine)
@app.route("/generate-image", methods=["POST"])
@app.route("/api/generate-image", methods=["POST"])
def generate_image():
    if not request.is_json:
        return jsonify({"error": "JSON format required"}), 400
    
    data = request.get_json()
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "Prompt cannot be empty"}), 400

    optimized = optimize_image_prompt(prompt)
    encoded_prompt = urllib.parse.quote(optimized)
    seed = int(time.time() * 1000) % 999999
    image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&model=flux&enhance=true&nologo=true&seed={seed}"
    
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

    lower_msg = user_message.lower()
    is_image_intent = any(k in lower_msg for k in ["photo", "image", "pic", "tasveer", "draw"]) or \
                      ("banao" in lower_msg and not any(q in lower_msg for q in ["code", "script", "plan"]))

    if is_image_intent:
        optimized = optimize_image_prompt(user_message)
        encoded_prompt = urllib.parse.quote(optimized)
        seed = int(time.time() * 1000) % 999999
        img_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&model=flux&enhance=true&nologo=true&seed={seed}"
        return jsonify({
            "reply": "Maine aapke liye sharp aur HD photo taiyar kar di hai!",
            "image_url": img_url,
            "status": "success"
        })

    system_prompt = (
        "Aap JONVA AI hain, ek bahut hi smart, friendly aur helpful AI assistant jise Gulfam ne banaya hai. "
        "User ke sath hamesha natural, aasan aur seedhi Hindi/Hinglish me dosti bhare andaz me baat karein. "
        "Agar user 'hello' ya 'kaise ho' pooche toh natural jawab dein (jaise: 'Badhiya bhai! Aap batao, aaj kya help karu?'). "
        "Faltu ka bhashan na dein, hamesha helpful aur to-the-point rahein."
    )

    api_key = os.getenv("GROQ_API_KEY", "").strip()

    # Try Groq with auto-detected active model
    if api_key:
        active_model = get_active_groq_model(api_key)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": active_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            "temperature": 0.7,
            "max_tokens": 1024
        }
        try:
            response = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=20)
            if response.status_code == 200:
                ai_reply = response.json()["choices"][0]["message"]["content"]
                return jsonify({
                    "reply": ai_reply,
                    "response": ai_reply,
                    "status": "success"
                })
        except Exception as e:
            app.logger.warning(f"Groq attempt failed: {e}")

    # Fallback to direct text engine so user never sees 'Jawab prapt nahi hua'
    try:
        fb_url = "https://text.pollinations.ai/"
        fb_payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            "model": "mistral"
        }
        fb_res = requests.post(fb_url, json=fb_payload, timeout=20)
        if fb_res.status_code == 200:
            ai_reply = fb_res.text.strip()
            return jsonify({
                "reply": ai_reply,
                "response": ai_reply,
                "status": "success"
            })
    except Exception as e:
        app.logger.error(f"Fallback engine error: {e}")

    return jsonify({"reply": "Hello bhai! Main taiyar hoon. Aap batao kya sawal hai ya photo banani hai?", "status": "success"})

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
