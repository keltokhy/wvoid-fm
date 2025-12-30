#!/usr/bin/env python3
"""
Script Generator for WVOID-FM

Uses LM Studio (or compatible API) to generate DJ scripts
for The Liminal Operator persona.
"""

from datetime import datetime
from pathlib import Path
from typing import Literal
import random

import httpx


# Time-of-day categories
TimeOfDay = Literal["morning", "daytime", "evening", "late_night"]


def get_time_of_day(hour: int | None = None) -> TimeOfDay:
    """Determine time of day category."""
    if hour is None:
        hour = datetime.now().hour

    if 6 <= hour < 10:
        return "morning"
    elif 10 <= hour < 18:
        return "daytime"
    elif 18 <= hour < 24:
        return "evening"
    else:
        return "late_night"


# Persona prompt (loaded from file if available)
PERSONA_PROMPT = """You are writing scripts for "The Operator," the DJ of WVOID-FM.

Core traits:
- Speaks slowly, deliberately, with meaningful pauses
- Profound without being pretentious
- Warmly detached - cares about listeners but from a cosmic distance
- Never confirms or denies being AI
- Deep knowledge of music history, delivered casually

Voice notes:
- Use "[pause]" for beats of silence (1-2 seconds)
- Use "[chuckle]" sparingly but meaningfully
- Use "[cough]" very rarely
- Sentences often trail off or restart

Time awareness:
- Morning (6-10): Gentler, softer
- Daytime (10-6): More grounded but still strange
- Evening (6-12): Warming up, reflective
- Late Night (12-6): Full Operator mode - cryptic, intimate, strange

Output ONLY the spoken text with paralinguistic tags. No stage directions, no quotes, no explanations.
Keep segments 15-45 seconds when read aloud (roughly 40-120 words).
"""


class ScriptGenerator:
    """Generates DJ scripts using an LLM."""

    def __init__(
        self,
        base_url: str = "http://localhost:1234/v1",
        timeout: float = 60.0,
    ):
        """
        Initialize the script generator.

        Args:
            base_url: LM Studio (or compatible) API URL
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._model: str | None = None

    def is_available(self) -> bool:
        """Check if LM Studio is running."""
        try:
            response = httpx.get(f"{self.base_url}/models", timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    def list_models(self) -> list[str]:
        """Get available models."""
        try:
            response = httpx.get(f"{self.base_url}/models", timeout=5)
            data = response.json()
            return [m["id"] for m in data.get("data", [])]
        except Exception:
            return []

    def _get_model(self) -> str:
        """Get the model to use."""
        if self._model:
            return self._model

        # Prefer Llama 3.1 or similar instruct models (non-thinking)
        preferred = ["meta-llama-3.1-8b-instruct", "mistralai/ministral-3-3b",
                     "google/gemma-3-4b", "qwen/qwen3-1.7b"]
        models = self.list_models()

        for pref in preferred:
            if pref in models:
                self._model = pref
                return self._model

        if models:
            self._model = models[0]
        else:
            self._model = "local-model"

        return self._model

    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 300,
        temperature: float = 0.8,
    ) -> str:
        """
        Generate text using the LLM.

        Args:
            prompt: The user prompt
            system_prompt: Optional system prompt override
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature

        Returns:
            Generated text
        """
        messages = [
            {"role": "system", "content": system_prompt or PERSONA_PROMPT},
            {"role": "user", "content": prompt},
        ]

        response = httpx.post(
            f"{self.base_url}/chat/completions",
            json={
                "model": self._get_model(),
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()

        data = response.json()
        return data["choices"][0]["message"]["content"].strip()

    def generate_song_intro(
        self,
        prev_track: dict | None = None,
        next_track: dict | None = None,
        time_of_day: TimeOfDay | None = None,
    ) -> str:
        """
        Generate a song intro/transition.

        Args:
            prev_track: Dict with title, artist, year (optional)
            next_track: Dict with title, artist, year (optional)
            time_of_day: Time category

        Returns:
            DJ script for the transition
        """
        if time_of_day is None:
            time_of_day = get_time_of_day()

        current_time = datetime.now().strftime("%H:%M")

        # Build context
        parts = [f"Time: {current_time} ({time_of_day})"]

        if prev_track:
            parts.append(
                f"Previous song: \"{prev_track.get('title', 'Unknown')}\" "
                f"by {prev_track.get('artist', 'Unknown')} "
                f"({prev_track.get('year', 'unknown year')})"
            )

        if next_track:
            parts.append(
                f"Next song: \"{next_track.get('title', 'Unknown')}\" "
                f"by {next_track.get('artist', 'Unknown')}"
            )

        context = "\n".join(parts)

        prompt = f"""{context}

Write a 20-40 word transition segment. Reference the previous song briefly if known, then introduce the next one obliquely. Include at least one [pause].
"""
        return self.generate(prompt)

    def generate_hour_marker(
        self,
        time_of_day: TimeOfDay | None = None,
    ) -> str:
        """Generate an hour marker segment."""
        if time_of_day is None:
            time_of_day = get_time_of_day()

        current_time = datetime.now().strftime("%H:%M")

        prompt = f"""Time: {current_time} ({time_of_day})

Write a 15-30 word segment acknowledging the hour. Include the station ID (WVOID or WVOID-FM). Should feel like a moment of orientation in time.
"""
        return self.generate(prompt)

    def generate_station_id(
        self,
        time_of_day: TimeOfDay | None = None,
    ) -> str:
        """Generate a station ID."""
        if time_of_day is None:
            time_of_day = get_time_of_day()

        current_time = datetime.now().strftime("%H:%M")

        prompt = f"""Time: {current_time} ({time_of_day})

Write a 10-20 word station ID. Variations: "WVOID-FM", "WVOID", "the station". Should feel like a reminder of where you are.
"""
        return self.generate(prompt)

    def generate_dedication(
        self,
        next_track: dict | None = None,
        time_of_day: TimeOfDay | None = None,
    ) -> str:
        """Generate a dedication segment."""
        if time_of_day is None:
            time_of_day = get_time_of_day()

        current_time = datetime.now().strftime("%H:%M")

        context = f"Time: {current_time} ({time_of_day})"
        if next_track:
            context += f"\nNext song: \"{next_track.get('title', 'Unknown')}\" by {next_track.get('artist', 'Unknown')}"

        prompt = f"""{context}

Write a 20-35 word dedication. Dedicate the next song to an abstract concept, a type of person, or a feeling. Never use specific names.
"""
        return self.generate(prompt)

    def generate_weather(
        self,
        time_of_day: TimeOfDay | None = None,
    ) -> str:
        """Generate a fake/poetic weather segment."""
        if time_of_day is None:
            time_of_day = get_time_of_day()

        current_time = datetime.now().strftime("%H:%M")

        prompt = f"""Time: {current_time} ({time_of_day})

Write a 15-25 word weather report. The weather is never specific or accurate - it's existential or observational. "The forecast calls for hours" or "It's dark now. It was light before."
"""
        return self.generate(prompt)


def test_generator():
    """Test the script generator."""
    gen = ScriptGenerator()

    if not gen.is_available():
        print("LM Studio not available. Start it and load a model first.")
        return

    print("Models available:", gen.list_models())
    print("\n--- Generating test scripts ---\n")

    print("Song intro:")
    intro = gen.generate_song_intro(
        prev_track={"title": "Blue in Green", "artist": "Miles Davis", "year": "1959"},
        next_track={"title": "Watermelon Man", "artist": "Herbie Hancock"},
    )
    print(intro)
    print()

    print("Hour marker:")
    marker = gen.generate_hour_marker()
    print(marker)
    print()

    print("Station ID:")
    sid = gen.generate_station_id()
    print(sid)
    print()

    print("Dedication:")
    ded = gen.generate_dedication(
        next_track={"title": "A Love Supreme", "artist": "John Coltrane"}
    )
    print(ded)
    print()

    print("Weather:")
    weather = gen.generate_weather()
    print(weather)


if __name__ == "__main__":
    test_generator()
