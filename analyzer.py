"""Anthropic API fallback: the same two roles as the `claude -p` backend, over an API key."""

from __future__ import annotations

import base64
import io

from PIL import Image
import log

L = log.get("analyzer")

MAX_IMAGE_WIDTH = 800


def optimize_image(img: Image.Image) -> str:
    """Resize + JPEG encode for fast API transfer."""
    w, h = img.size
    if w > MAX_IMAGE_WIDTH:
        ratio = MAX_IMAGE_WIDTH / w
        img = img.resize((MAX_IMAGE_WIDTH, int(h * ratio)), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    b64 = base64.standard_b64encode(buf.getvalue()).decode("utf-8")
    L.debug(f"Image optimized: {w}x{h} → {img.size[0]}x{img.size[1]}, {len(b64)} chars")
    return b64


class ApiBackend:
    """Fallback for machines without a logged-in `claude`: same roles over the Anthropic API."""

    name = "API"

    def __init__(self, api_key: str, model: str, eyes_system: str, voice_system: str):
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self._eyes_system = eyes_system
        self._voice_system = voice_system
        self._history: list[dict] = []
        self._seed = ""
        self.voice_turns = 0
        L.info(f"API-Backend bereit: model={model}, key=...{api_key[-8:]}")

    @staticmethod
    def _image_block(img: Image.Image) -> dict:
        return {"type": "image", "source": {
            "type": "base64", "media_type": "image/jpeg", "data": optimize_image(img)}}

    def read_table(self, img: Image.Image) -> dict | None:
        import brain
        response = self.client.messages.create(
            model=self.model, max_tokens=1500, system=self._eyes_system,
            messages=[{"role": "user", "content": [
                self._image_block(img), {"type": "text", "text": "Lies den Tisch."}]}],
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        return brain.extract_json(text)

    def new_hand(self):
        pass  # table reads are stateless here

    def ask(self, text: str, img: Image.Image | None = None, on_delta=None, cancelled=None) -> str:
        if self._seed:
            text, self._seed = f"[Bisherige Session]\n{self._seed}\n\n{text}", ""
        content = [{"type": "text", "text": text}]
        if img is not None:
            content.insert(0, self._image_block(img))
        collected = ""
        with self.client.messages.stream(
            model=self.model, max_tokens=1500, system=self._voice_system,
            messages=self._history + [{"role": "user", "content": content}],
        ) as stream:
            for delta in stream.text_stream:
                collected += delta
                if on_delta and not (cancelled and cancelled()):
                    on_delta(delta)
        # keep the screenshot out of the history, the text state is enough for later turns
        self._history += [{"role": "user", "content": text},
                          {"role": "assistant", "content": collected}]
        self.voice_turns += 1
        return collected

    def reset_conversation(self, seed: str = ""):
        self._history = []
        self._seed = seed
        self.voice_turns = 0

    def close(self):
        pass
