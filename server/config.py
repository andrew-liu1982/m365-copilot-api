"""Server configuration — shared constants."""

import os

# The single model id this bridge advertises (Copilot has no model selector).
MODEL_NAME = "copilot"

COPILOT_MODE = "m365" 

# Self-imposed rate limit (Copilot publishes none). Tune to whatever ceiling the
# probe in tests/ratelimit.py shows your account tolerates.
#   RATE_LIMIT_RPM   requests/minute the bridge will accept; 0 disables limiting.
#   RATE_LIMIT_BURST max requests allowed back-to-back before pacing kicks in.
# Default 10 rpm provides conservative pacing for stable operation.
# Tune upward (15-20 rpm) for higher throughput, or set 0 to disable.
RATE_LIMIT_RPM = float(os.environ.get("RATE_LIMIT_RPM", "10"))  # 10 rpm ≈ 6s per call
RATE_LIMIT_BURST = int(os.environ.get("RATE_LIMIT_BURST", "4"))

# M365 vs consumer Copilot mode
COPILOT_MODE = os.environ.get("COPILOT_MODE", "m365")
