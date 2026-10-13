"""Gemini API client: model fallback, retries with backoff, JSON mode.
The API key is sent in a header (never in the URL) so it cannot leak into logs."""
import json
import os
import random
import re
import time

import requests

from .config import CFG
from .util import log

API = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"


class GeminiError(RuntimeError):
    pass


def _extract(data: dict) -> str:
    cands = data.get("candidates") or []
    if not cands:
        raise GeminiError(f"No candidates in response: {str(data)[:300]}")
    cand = cands[0]
    if cand.get("finishReason") == "MAX_TOKENS":
        raise GeminiError("Response was cut off (MAX_TOKENS)")
    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not text.strip():
        raise GeminiError(f"Empty text in response (finishReason={cand.get('finishReason')})")
    return text


def generate(prompt: str, json_mode: bool = True, temperature: float = 0.9) -> str:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise GeminiError("GEMINI_API_KEY is not set")
    models = [CFG["gemini_model"]] + [m for m in CFG.get("gemini_fallbacks", []) if m != CFG["gemini_model"]]
    gen_cfg = {"temperature": temperature, "maxOutputTokens": 8192}
    if json_mode:
        gen_cfg["responseMimeType"] = "application/json"
    body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": gen_cfg}
    last = "unknown error"
    for model in models:
        for attempt in range(4):
            try:
                r = requests.post(API.format(model), headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                                  json=body, timeout=90)
            except requests.RequestException as e:
                last = f"{model}: network error {type(e).__name__}"
                time.sleep(2 ** attempt + random.random())
                continue
            if r.status_code == 200:
                try:
                    return _extract(r.json())
                except GeminiError as e:
                    last = f"{model}: {e}"
                    continue
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"{model}: HTTP {r.status_code}"
                time.sleep(2 ** attempt * 2 + random.random())
                continue
            last = f"{model}: HTTP {r.status_code} {r.text[:200]}"
            log(f"[Gemini] {last} -> trying next model")
            break
        else:
            log(f"[Gemini] {model} kept failing -> trying next model")
    raise GeminiError(f"All Gemini models failed. Last error: {last}")


def generate_json(prompt: str, temperature: float = 0.9):
    text = generate(prompt, json_mode=True, temperature=temperature).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise GeminiError(f"Gemini did not return valid JSON: {e}") from e
