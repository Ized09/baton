"""Cost guard: per-call input limit, daily cap, token logging.

Nothing here calls a network API. The guard is enforced before any
extraction, and every extraction records its (estimated or real) usage.
Estimates are always labelled estimated=True; the real Nebius adapter will
report measured usage from the API response.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path


class CostGuardError(RuntimeError):
    pass


class CostGuard:
    def __init__(
        self,
        *,
        max_input_chars: int = 120_000,
        daily_token_cap: int = 200_000,
        log_path: Path | str | None = None,
    ) -> None:
        self.max_input_chars = max_input_chars
        self.daily_token_cap = daily_token_cap
        self.log_path = Path(log_path) if log_path else None
        self._entries: list[dict] = []
        if self.log_path and self.log_path.exists():
            for line in self.log_path.read_text().splitlines():
                line = line.strip()
                if line:
                    self._entries.append(json.loads(line))

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Rough estimate: ~4 chars per token. Always labelled estimated."""
        return max(1, len(text) // 4)

    def check_input(self, text: str) -> int:
        """Enforce the per-call input limit. Returns the token estimate."""
        if len(text) > self.max_input_chars:
            raise CostGuardError(
                f"input of {len(text)} chars exceeds per-call limit of {self.max_input_chars}"
            )
        return self.estimate_tokens(text)

    def daily_total(self, day: date | None = None) -> int:
        day = day or date.today()
        return sum(
            e["tokens_in"] + e["tokens_out"]
            for e in self._entries
            if e.get("day") == day.isoformat()
        )

    def remaining(self, day: date | None = None) -> int:
        return max(0, self.daily_token_cap - self.daily_total(day))

    def record(
        self,
        *,
        model: str,
        purpose: str,
        tokens_in: int,
        tokens_out: int,
        estimated: bool,
    ) -> dict:
        """Log one call. Raises CostGuardError if it would exceed the daily cap."""
        today = date.today()
        if self.daily_total(today) + tokens_in + tokens_out > self.daily_token_cap:
            raise CostGuardError(
                f"daily token cap of {self.daily_token_cap} would be exceeded "
                f"({self.daily_total(today)} already used)"
            )
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "day": today.isoformat(),
            "model": model,
            "purpose": purpose,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "estimated": estimated,
        }
        self._entries.append(entry)
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a") as f:
                f.write(json.dumps(entry) + "\n")
        return entry
