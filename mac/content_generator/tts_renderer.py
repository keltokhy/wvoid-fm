#!/usr/bin/env python3
"""
TTS Renderer for WVOID-FM

Uses Chatterbox TTS to render DJ scripts into audio segments.
Supports the Operator's paralinguistic tags: [pause], [chuckle], [cough]
"""

import os
import re
import sys
from pathlib import Path
from datetime import datetime

# Add chatterbox to path
# (Now installed via uv)


def get_device() -> str:
    """Get the best available device."""
    import torch
    if torch.backends.mps.is_available():
        return "mps"
    elif torch.cuda.is_available():
        return "cuda"
    return "cpu"


def preprocess_script(text: str) -> str:
    """
    Convert Operator-style tags to Chatterbox Turbo tags.

    Mapping:
    - [pause] -> ... (ellipsis creates natural pause)
    - [chuckle] -> [chuckle] (native Turbo tag)
    - [cough] -> [cough] (native Turbo tag)
    - [laugh] -> [laugh] (native Turbo tag)
    """
    # [pause] -> ellipsis for natural pause
    text = re.sub(r'\[pause\]', '...', text)

    # Keep native Turbo tags as-is
    # [chuckle], [cough], [laugh] are already supported

    # Clean up multiple spaces
    text = re.sub(r'\s+', ' ', text).strip()

    return text


class TTSRenderer:
    """Renders text to speech using Chatterbox Turbo."""

    def __init__(self, voice_reference: Path | str | None = None):
        """
        Initialize the TTS renderer.

        Args:
            voice_reference: Path to a voice sample for cloning (10-15 seconds recommended)
        """
        self.device = get_device()
        self.model = None
        self.voice_reference = Path(voice_reference) if voice_reference else None
        self._loaded = False

    def load(self):
        """Load the TTS model."""
        if self._loaded:
            return

        print(f"Loading Chatterbox Turbo on {self.device}...")

        # Patch perth watermarker if needed
        try:
            import perth
            if not hasattr(perth, "PerthImplicitWatermarker") or perth.PerthImplicitWatermarker is None:
                perth.PerthImplicitWatermarker = getattr(perth, "DummyWatermarker", None)
        except (ImportError, AttributeError):
            pass

        from chatterbox.tts import ChatterboxTTS

        self.model = ChatterboxTTS.from_pretrained(device=self.device)

        if self.voice_reference and self.voice_reference.exists():
            print(f"Preparing voice from: {self.voice_reference}")
            self.model.prepare_conditionals(
                str(self.voice_reference),
                exaggeration=0.5
            )

        self._loaded = True
        print("Model loaded!")

    def render(
        self,
        text: str,
        output_path: Path | str,
        exaggeration: float = 0.5,
        cfg_weight: float = 0.5,
        temperature: float = 0.8,
    ) -> Path:
        """
        Render text to audio file.

        Args:
            text: The DJ script to render (with [pause], [chuckle], etc.)
            output_path: Where to save the audio file
            exaggeration: Voice exaggeration (0.0-1.0)
            cfg_weight: Classifier-free guidance weight
            temperature: Sampling temperature

        Returns:
            Path to the generated audio file
        """
        if not self._loaded:
            self.load()

        import torchaudio as ta

        # Preprocess the script
        processed = preprocess_script(text)
        print(f"Rendering: {processed[:80]}...")

        # Generate audio
        wav = self.model.generate(
            processed,
            exaggeration=exaggeration,
            cfg_weight=cfg_weight,
            temperature=temperature,
        )

        # Save to file
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Use soundfile directly to avoid torchcodec issues
        import soundfile as sf
        
        # Convert to numpy (ensure CPU)
        wav_np = wav.detach().cpu().numpy()
        
        # soundfile expects (time, channels) or (time,)
        # torchaudio usually produces (channels, time)
        if wav_np.ndim == 2 and wav_np.shape[0] < wav_np.shape[1]:
            wav_np = wav_np.T
            
        sf.write(str(output_path), wav_np, 24000)
        print(f"Saved: {output_path}")

        return output_path


def generate_test_segment():
    """Generate a test DJ segment."""
    voice_ref = Path(__file__).parent.parent / "voice_reference" / "operator_voice.wav"

    renderer = TTSRenderer(voice_reference=voice_ref if voice_ref.exists() else None)

    test_script = """
    Mmm. [pause] It's late. You're still here. [chuckle]
    That means something. Probably.
    [pause]
    WVOID-FM. Still broadcasting.
    """

    output_dir = Path(__file__).parent.parent.parent / "output"
    output_path = output_dir / f"test_segment_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"

    renderer.render(test_script, output_path)
    print(f"Test segment saved to: {output_path}")


if __name__ == "__main__":
    generate_test_segment()
