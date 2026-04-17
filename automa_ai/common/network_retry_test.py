from automa_ai.common.network_retry import (
    compute_retry_delay,
    is_retryable_network_error,
)


class DummyStatusError(Exception):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"status={status_code}")


def test_is_retryable_network_error_matches_status_code():
    assert is_retryable_network_error(DummyStatusError(503)) is True
    assert is_retryable_network_error(DummyStatusError(400)) is False


def test_is_retryable_network_error_matches_message():
    assert (
        is_retryable_network_error(
            RuntimeError("Service Unavailable: model experiencing high demand")
        )
        is True
    )


def test_compute_retry_delay_respects_zero_attempt():
    assert compute_retry_delay(0) == 0.0


def test_compute_retry_delay_respects_max_delay():
    delay = compute_retry_delay(10, base_delay_seconds=1.0, max_delay_seconds=2.0)

    assert 0.0 <= delay <= 2.0
