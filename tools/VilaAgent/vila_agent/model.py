import json
import os
import urllib.error
import urllib.request


SYSTEM_PROMPT = """You are VilaAgent, a careful coding agent.
Return only valid JSON with these keys:
- plan: string
- summary: string
- unified_diff: string containing a git-compatible unified diff, or empty string
- tests: array of suggested test commands
- risks: array of strings

Rules:
- Do not delete existing features unless the user explicitly asks.
- Keep the patch focused.
- Prefer small, reviewable changes.
- Do not include secrets.
- If context is insufficient, return a plan and empty unified_diff.
- The unified_diff must be applicable with git apply from the repo root.
"""


def fallback_response(task, reason):
    return {
        "plan": (
            "AI model was not available. Review the saved context, then configure OPENAI_API_KEY "
            "and run the agent again."
        ),
        "summary": f"Could not call AI model for task: {task}. Reason: {reason}",
        "unified_diff": "",
        "tests": [],
        "risks": ["No code patch generated because the AI provider was unavailable."],
    }


def ask_model(task, context, model="gpt-5.2"):
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return fallback_response(task, "OPENAI_API_KEY is missing.")

    payload = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": SYSTEM_PROMPT}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": f"Task:\n{task}\n\nProject context:\n{context}"}],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "vila_agent_patch",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "plan": {"type": "string"},
                        "summary": {"type": "string"},
                        "unified_diff": {"type": "string"},
                        "tests": {"type": "array", "items": {"type": "string"}},
                        "risks": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["plan", "summary", "unified_diff", "tests", "risks"],
                },
            }
        },
        "max_output_tokens": 5000,
    }

    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return fallback_response(task, exc.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        return fallback_response(task, str(exc))

    output_text = data.get("output_text", "")
    if not output_text:
        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("text"):
                    output_text = content["text"]
                    break
            if output_text:
                break

    if not output_text:
        return fallback_response(task, "Model returned no text.")

    try:
        parsed = json.loads(output_text)
    except json.JSONDecodeError:
        return fallback_response(task, f"Model returned invalid JSON: {output_text[:500]}")

    return parsed

