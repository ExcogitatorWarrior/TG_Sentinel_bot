import os
import requests

MODEL_DIR = "models"
MODEL_FILE = "mistral-7b-instruct-v0.2.Q4_K_M.gguf"
MODEL_URL = (
    "https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF/"
    "resolve/main/mistral-7b-instruct-v0.2.Q4_K_M.gguf"
)

os.makedirs(MODEL_DIR, exist_ok=True)
model_path = os.path.join(MODEL_DIR, MODEL_FILE)

def download_model():
    if os.path.exists(model_path):
        print(f"✅ Model already exists at {model_path}")
        return

    print(f"⬇️ Downloading model from {MODEL_URL}")
    response = requests.get(MODEL_URL, stream=True)
    response.raise_for_status()

    total_size = int(response.headers.get("content-length", 0))
    chunk_size = 8192
    downloaded = 0

    with open(model_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=chunk_size):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                done = int(50 * downloaded / total_size) if total_size else 0
                print(f"\r[{'=' * done}{' ' * (50-done)}] {downloaded/1e6:.2f} MB", end="")

    print(f"\n✅ Download complete: {model_path}")

if __name__ == "__main__":
    download_model()
