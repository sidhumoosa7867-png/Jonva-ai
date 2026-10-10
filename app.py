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
CANDIDATE_MODELS = [
    "llama-3.3-70b-versatile",
    "llama3-8b-8192",
    "mixtral-8x7b-32768"
]
active_model = CANDIDATE_MODELS[0]

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

def optimize_image_prompt(raw_prompt):
    # Auto-add detail boosters so faces and textures render sharply
    clean = raw_prompt.strip()
    for filler in ["generate an image of", "generate image of", "photo banao", "image banao", "photo of", "image of", "tasveer banao"]:
        clean = clean.replace(filler, "")
    clean = clean.strip() or raw_prompt
    
    # Detail booster for clean, photorealistic faces
    boosted = f"{clean}, highly detailed, sharp facial features, flawless face, 8k resolution, photorealistic, cinematic lighting, ultra high definition"
    return boosted

# Real AI Image Generator (Flux + Enhanced Face Rendering)
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
    # enhance=true ensures the AI engine expands facial details and quality
    image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&model=flux&enhance=true&nologo=true&seed={seed}"
    
    return jsonify({
        "status": "success",
        "image_url": image_url,
        "prompt": prompt
    })

@app.route("/chat", methods=["POST"])
@app.route("/api/chat", methods=["POST"])
def chat():
    global active_model
    if not request.is_json:
        return jsonify({"error": "JSON format required."}), 400

    data = request.get_json()
    user_message = data.get("message") or data.get("prompt") or ""
    user_message = str(user_message).strip()

    if not user_message:
        return jsonify({"error": "Message cannot be empty."}), 400

    lower_msg = user_message.lower()
    img_keywords = [
        "image", "photo", "pic", "picture", "banao", "tasveer",
        "draw", "generate", "superman", "batman", "avatar", "wallpaper"
    ]
    # Check if user is asking for image creation
    is_image_intent = any(k in lower_msg for k in ["photo", "image", "pic", "tasveer", "draw"]) or \
                      ("banao" in lower_msg and not any(q in lower_msg for q in ["code", "script", "plan"]))

    if is_image_intent:
        optimized = optimize_image_prompt(user_message)
        encoded_prompt = urllib.parse.quote(optimized)
        seed = int(time.time() * 1000) % 999999
        img_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&model=flux&enhance=true&nologo=true&seed={seed}"
        return jsonify({
            "reply": f"Maine aapke liye sharp aur HD photo taiyar kar di hai!",
            "image_url": img_url,
            "status": "success"
        })

    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return jsonify({"error": "Groq API Key is missing in Render environment."}), 500

    system_prompt = (
        "Aap JONVA AI hain, ek bahut hi smart, friendly aur helpful AI assistant jise Gulfam ne banaya hai. "
        "User ke sath hamesha seedhi, aasan aur natural Hindi/Hinglish me baat karein, jaise ek sachhe dost aur intelligent saathi se karte hain. "
        "Agar user 'hello' ya 'kaise ho' pooche, to natural dhang se jawab dein (jaise: 'Badhiya bhai! Aap batao, aaj kya help karu ya kya create karna hai?'). "
        "Lamba bekar bhashan na dein, hamesha point-to-point aur helpful banein."
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    models_to_test = [active_model] + [m for m in CANDIDATE_MODELS if m != active_model]
    last_error = ""

    for model_name in models_to_test:
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            "temperature": 0.7,
            "max_tokens": 1024
        }
        try:
            response = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=25)
            if response.status_code == 200:
                active_model = model_name
                res_data = response.json()
                ai_reply = res_data["choices"][0]["message"]["content"]
                return jsonify({
                    "reply": ai_reply,
                    "response": ai_reply,
                    "status": "success"
                })
            else:
                last_error = response.json().get("error", {}).get("message", "API error")
        except Exception as e:
            last_error = str(e)

    return jsonify({"error": f"AI error: {last_error}"}), 500

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
