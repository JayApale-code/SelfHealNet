from typing import Protocol


class SmsProvider(Protocol):
    def send_otp(self, phone_number: str, otp: str) -> None:
        """Deliver an OTP without logging or returning its contents."""


class DevelopmentMockSmsProvider:
    def send_otp(self, phone_number: str, otp: str) -> None:
        """Intentionally do not deliver or expose mock messages as real SMS."""


def get_sms_provider() -> SmsProvider:
    return DevelopmentMockSmsProvider()
