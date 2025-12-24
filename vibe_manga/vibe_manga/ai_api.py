import requests
import json
import logging
import re
import os
from typing import Optional, Dict, Any, Union, Literal, List

from .constants import (
    REMOTE_AI_BASE_URL, REMOTE_AI_API_KEY, REMOTE_AI_MODEL,
    LOCAL_AI_BASE_URL, LOCAL_AI_API_KEY, LOCAL_AI_MODEL,
    AI_TIMEOUT, AI_MAX_RETRIES, ROLE_CONFIG
)

logger = logging.getLogger(__name__)

class TokenTracker:
    """Tracks token usage across the session."""
    def __init__(self):
        self.usage = {} # model_name -> {"prompt": int, "completion": int}

    def add_usage(self, model: str, prompt: int, completion: int):
        if model not in self.usage:
            self.usage[model] = {"prompt": 0, "completion": 0}
        self.usage[model]["prompt"] += prompt
        self.usage[model]["completion"] += completion

    def get_summary(self) -> Dict[str, Dict[str, int]]:
        return self.usage

# Global instance
tracker = TokenTracker()

def clean_ai_response(text: str) -> str:
    """
    Removes 'thinking' or 'reasoning' blocks often output by models like DeepSeek R1, Perplexity Sonar, or Claude.
    Handles <think>...</think>, <thinking>...</thinking>, <reasoning>...</reasoning>, and other common artifacts.
    """
    if not text:
        return ""
    
    # Remove standard XML-style thinking tags
    # re.DOTALL is crucial to match across newlines
    # We clean sequentially to handle nested or multiple blocks if necessary
    cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    cleaned = re.sub(r'<thinking>.*?</thinking>', '', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'<reasoning>.*?</reasoning>', '', cleaned, flags=re.DOTALL)
    
    # Sometimes models output "Here is my thought process: ..."
    # This is harder to catch without false positives, so we rely on extract_json
    # finding the actual JSON object later.
    
    return cleaned.strip()

def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """
    Extracts the first JSON object found in a string.
    Resilient to preambles, postambles, and markdown blocks.
    """
    if not text:
        return None

    # 1. Clean thinking/reasoning artifacts
    text = clean_ai_response(text)

    # 2. Try simple load first
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # 3. Handle Markdown JSON blocks (```json ... ```)
    md_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL | re.IGNORECASE)
    if md_match:
        try:
            return json.loads(md_match.group(1))
        except json.JSONDecodeError:
            pass

    # 4. Aggressive search for first { and last }
    first_brace = text.find('{')
    last_brace = text.rfind('}')
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        json_candidate = text[first_brace:last_brace + 1]
        try:
            return json.loads(json_candidate)
        except json.JSONDecodeError:
            pass
            
    logger.warning(f"Failed to extract JSON from AI response. Preview: {text[:200]}...")
    return None

def get_available_models(provider: Literal["remote", "local"]) -> List[str]:
    """
    Fetches available models from the provider's /v1/models endpoint.
    """
    if provider == "local":
        base_url = LOCAL_AI_BASE_URL
        api_key = LOCAL_AI_API_KEY
    else:
        base_url = REMOTE_AI_BASE_URL
        api_key = REMOTE_AI_API_KEY

    # Construct models endpoint
    # Remove /chat/completions if present
    endpoint = base_url.replace("/chat/completions", "").replace("/api/chat", "").replace("/api/generate", "")
    
    # Handle common local AI endpoint patterns (same logic as call_ai)
    if "/v1" not in endpoint and "/api/v1" not in endpoint:
        if "11434" in endpoint: # Ollama
             endpoint = endpoint.rstrip("/") + "/v1/models"
        elif "3000" in endpoint: # Open WebUI
             # Per official docs: GET /api/models
             if "/api/models" not in endpoint:
                 endpoint = endpoint.rstrip("/") + "/api/models"
        else:
             endpoint = endpoint.rstrip("/") + "/models"
    elif endpoint.endswith("/v1"):
        endpoint = endpoint + "/models"
    else:
        # If it's something like /v1/chat, just replace it
        endpoint = endpoint.rstrip("/") + "/models"

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    
    # OpenRouter specific headers
    if provider == "remote" and "openrouter" in base_url:
        headers["HTTP-Referer"] = "https://github.com/vibe-manga/vibemanga"
        headers["X-Title"] = "VibeManga CLI"

    try:
        response = requests.get(endpoint, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # OpenAI/Ollama format: {"data": [{"id": "model-name", ...}]}
        if "data" in data:
            return sorted([item["id"] for item in data["data"]])
        
        # Some custom endpoints might return just a list
        if isinstance(data, list):
             return sorted([item["id"] for item in data if "id" in item])
        
        return []

    except Exception as e:
        logger.warning(f"Failed to fetch models from {provider} ({endpoint}): {e}")
        return []

def call_ai(
    user_prompt: str,
    system_role: str,
    provider: Literal["remote", "local"] = "remote",
    model: Optional[str] = None,
    temperature: float = 0.7,
    json_mode: bool = True,
    status_callback: Optional[callable] = None
) -> Union[Dict[str, Any], str, None]:
    """
    Calls the configured AI backend with retries.
    """
    import time
    
    # Determine config based on provider
    if provider == "local":
        base_url = LOCAL_AI_BASE_URL
        api_key = LOCAL_AI_API_KEY
        target_model = model or LOCAL_AI_MODEL
    else:
        base_url = REMOTE_AI_BASE_URL
        api_key = REMOTE_AI_API_KEY
        target_model = model or REMOTE_AI_MODEL

    headers = {
        "Content-Type": "application/json",
    }
    
    # Auth
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    
    # OpenRouter specific headers for remote calls
    if provider == "remote" and "openrouter" in base_url:
        headers["HTTP-Referer"] = "https://github.com/vibe-manga/vibemanga"
        headers["X-Title"] = "VibeManga CLI"

    payload = {
        "model": target_model,
        "messages": [
            {"role": "system", "content": system_role},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": temperature,
        "stream": False
    }
    
    # OpenRouter specific headers for remote calls
    if provider == "remote" and "openrouter.ai" in base_url:
        payload["include_reasoning"] = False 

        
    # Endpoint construction
    endpoint = base_url.rstrip("/")
    
    # Handle common local AI/WebUI endpoint patterns
    # If the URL already looks like a complete endpoint, don't append
    if not any(x in endpoint.lower() for x in ["/chat/completions", "/api/chat", "/api/generate"]):
        # If it looks like a raw Ollama (11434)
        if "11434" in endpoint and "/v1" not in endpoint:
            endpoint = f"{endpoint}/v1/chat/completions"
        # If it looks like Open WebUI (3000)
        elif "3000" in endpoint:
            # Per official docs: POST /api/chat/completions
            if "/api" not in endpoint:
                 endpoint = f"{endpoint}/api/chat/completions"
            else:
                 endpoint = f"{endpoint}/chat/completions"
        elif "/v1" not in endpoint:
            # Fallback for general OpenAI-compatible backends that might need /v1
            # But we check if it's openrouter which definitely needs /v1
            if "openrouter.ai" in endpoint:
                endpoint = f"{endpoint}/v1/chat/completions"
            else:
                endpoint = f"{endpoint}/chat/completions"
        else:
            endpoint = f"{endpoint}/chat/completions"
    
    # Final cleanup of double slashes (except http://)
    # Re-verify it ends correctly if it was already partially set
    if endpoint.endswith("/v1"):
        endpoint = f"{endpoint}/chat/completions"

    for attempt in range(AI_MAX_RETRIES + 1):
        try:
            msg = f"Calling AI ({provider}) [Attempt {attempt+1}/{AI_MAX_RETRIES+1}]"
            logger.debug(f"{msg}: {endpoint} with model {target_model}")
            if status_callback:
                status_callback(msg)

            response = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=AI_TIMEOUT
            )
            response.raise_for_status()
            
            data = response.json()
            
            # Track usage
            usage = data.get("usage")
            if usage:
                # Standard OpenAI field names: prompt_tokens, completion_tokens
                # Ollama/Local might vary slightly but many follow OpenAI now
                p_tokens = usage.get("prompt_tokens", usage.get("input_tokens", 0))
                c_tokens = usage.get("completion_tokens", usage.get("output_tokens", 0))
                tracker.add_usage(target_model, p_tokens, c_tokens)

            # Standard OpenAI format
            if 'choices' in data and len(data['choices']) > 0:
                content = data['choices'][0]['message']['content']
            else:
                logger.error(f"Unexpected API response format from {provider}: {data.keys()}")
                logger.debug(f"Full Response: {data}")
                if attempt < AI_MAX_RETRIES:
                    continue
                return None
            
            # Clean logic is now handled inside extract_json for JSON mode,
            # but for text mode we should also clean it.
            if json_mode:
                parsed = extract_json(content)
                if parsed:
                    return parsed
                else:
                    msg = f"AI response JSON parse failed (Attempt {attempt+1}/{AI_MAX_RETRIES+1})"
                    logger.debug(msg)
                    if status_callback:
                        status_callback(f"[yellow]{msg}[/yellow]")
                    if attempt < AI_MAX_RETRIES:
                        time.sleep(1)
                        continue
            
            return clean_ai_response(content)

        except requests.exceptions.RequestException as e:
            status_code = e.response.status_code if e.response is not None else "Unknown"
            if status_code == 401:
                logger.error(f"AI API Unauthorized (401). Check your API Key for {provider} in .env.")
                return None # Don't retry auth fails
            elif status_code == 403:
                logger.error(f"AI API Forbidden (403). Your API Key for {provider} may not have access to model '{target_model}' or the provider is blocking the request.")
                return None # Don't retry forbidden
            elif status_code == 429:
                 msg = "AI API Rate Limit (429). Retrying after delay..."
                 logger.debug(msg)
                 if status_callback:
                     status_callback(f"[yellow]{msg}[/yellow]")
                 time.sleep(2 * (attempt + 1))
                 continue
            else:
                logger.error(f"AI API Request Failed ({provider}) [Status {status_code}]: {e}")
            
            if getattr(e, 'response', None):
                 logger.error(f"Response Body: {e.response.text}")
                 logger.debug(f"Request Payload: {json.dumps(payload)}")
            
            if attempt < AI_MAX_RETRIES:
                time.sleep(1)
                continue
                
            return None
        except Exception as e:
            logger.error(f"Unexpected error in call_ai: {e}")
            if attempt < AI_MAX_RETRIES:
                continue
            return None

    return None