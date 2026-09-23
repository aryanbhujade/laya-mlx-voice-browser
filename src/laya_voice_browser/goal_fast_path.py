"""Small, whole-utterance direct controls. Never used on partial speech."""
import re


def direct_action(text: str) -> dict | None:
    phrase = text.strip().casefold().strip(" .!?,")
    # Strip courtesy only; never strip a connective or a preceding command.
    phrase = re.sub(r"^(?:(?:can|could|would) you\s+|please\s+)", "", phrase)
    phrase = re.sub(r"(?:\s+(?:please|thanks|thank you|for me))+$", "", phrase)
    if re.fullmatch(r"(?:go )?back", phrase):
        return {"type": "back"}
    if re.fullmatch(r"(?:go )?forward", phrase):
        return {"type": "forward"}
    match = re.fullmatch(r"scroll (up|down)(?: (a little|a bit|a page|one page|more))?", phrase)
    if match:
        return {"type": "scroll", "direction": match[1],
                "amount": "little" if match[2] in {"a little", "a bit"} else "page"}
    return None
