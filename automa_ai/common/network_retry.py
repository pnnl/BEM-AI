import random


RETRYABLE_NETWORK_STATUS_CODES = {429, 500, 502, 503, 504}
RETRYABLE_NETWORK_MARKERS = (
    "429",
    "500",
    "502",
    "503",
    "504",
    "service unavailable",
    "temporarily unavailable",
    "unavailable",
    "high demand",
    "try again later",
    "resource exhausted",
    "rate limit",
    "overloaded",
)


def compute_retry_delay(
    attempt: int,
    *,
    base_delay_seconds: float = 1.0,
    max_delay_seconds: float = 8.0,
) -> float:
    """Return an exponential backoff delay with bounded jitter.

    Algorithm:
    1. Start with `base_delay_seconds`.
    2. Double the delay on each retry attempt (`base * 2^(attempt - 1)`).
    3. Cap the exponential delay at `max_delay_seconds`.
    4. Add a small random jitter in `[0, base_delay_seconds]` so concurrent
       retries do not all fire at the same instant.
    5. Cap again at `max_delay_seconds` after adding jitter.

    This keeps early retries fast, spreads retry traffic across workers, and
    prevents unbounded sleep times on repeated failures.
    """
    if attempt <= 0 or base_delay_seconds <= 0:
        return 0.0

    # Exponential backoff: 1x, 2x, 4x, 8x, ... based on retry attempt count.
    delay = min(max_delay_seconds, base_delay_seconds * (2 ** (attempt - 1)))
    # Jitter avoids synchronized retries when many agents fail at once.
    jitter = random.uniform(0.0, base_delay_seconds)
    return min(max_delay_seconds, delay + jitter)


def is_retryable_network_error(exc: Exception) -> bool:
    current: BaseException | None = exc
    seen: set[int] = set()

    while current is not None and id(current) not in seen:
        seen.add(id(current))

        for attr in ("status_code", "code", "status"):
            value = getattr(current, attr, None)
            if isinstance(value, int) and value in RETRYABLE_NETWORK_STATUS_CODES:
                return True

        message = str(current).lower()
        if any(marker in message for marker in RETRYABLE_NETWORK_MARKERS):
            return True

        current = current.__cause__ or current.__context__

    return False
