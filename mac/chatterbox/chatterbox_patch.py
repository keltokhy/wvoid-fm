"""
Patch chatterbox to use DummyWatermarker instead of PerthImplicitWatermarker.

The perth package is a stub - PerthImplicitWatermarker is None without a license.
DummyWatermarker just returns the audio unchanged.
"""
import perth

# Monkey-patch perth to use DummyWatermarker
if perth.PerthImplicitWatermarker is None:
    perth.PerthImplicitWatermarker = perth.DummyWatermarker
