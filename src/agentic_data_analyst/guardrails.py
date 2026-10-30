"""Input guardrail: rejects messages before they reach the model, so they cost nothing."""

# A data question fits in a few hundred characters. The limit bounds cost per turn and the room for injected
# instructions, while leaving space for pasted context.
MAX_QUESTION_CHARS = 2000


def check_question(text: str) -> str | None:
    """Return a reply that rejects the message, or None if it may be sent to the model."""
    if not text.strip():
        return "Please type a question about the speedrun data."
    if len(text) > MAX_QUESTION_CHARS:
        return f"Please keep your question under {MAX_QUESTION_CHARS:,} characters."
    return None
