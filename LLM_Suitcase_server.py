# LLM_Suitcase_server.py
from fastapi import FastAPI
from pydantic import BaseModel
from llama_cpp import Llama
from fastapi.middleware.cors import CORSMiddleware
from config import LLM_CONFIG

# --------- Define the request model ---------
class PromptRequest(BaseModel):
    prompt: str
    max_tokens: int = 256

# --------- Initialize FastAPI ---------
app = FastAPI(title="Mistral API")

# Optional: Allow CORS so you can test from frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # change this to your frontend URL in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------- Initialize your Mistral model ---------
llm = Llama(**LLM_CONFIG)

# --------- API Endpoints ---------
@app.get("/")
def read_root():
    return {"message": "Mistral API is running."}

@app.post("/generate")
def generate_text(request: PromptRequest):
    prompt = request.prompt
    max_tokens = request.max_tokens

    # Generate response
    response_text = ""
    for chunk in llm(prompt=prompt, max_tokens=max_tokens, stream=True):
        response_text += chunk["choices"][0]["text"]

    return {"response": response_text}
