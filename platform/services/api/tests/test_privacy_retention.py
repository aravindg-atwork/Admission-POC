from app.storage.conversations import redact


def test_transcript_redaction_removes_common_sensitive_values():
    text = (
        "Email me at student@example.com or 9876543210. Aadhaar 1234 5678 9012. "
        "OTP 654321, account number 123456789012 and NEET application ID AB12345678."
    )
    safe = redact(text)
    for secret in ("student@example.com", "9876543210", "1234 5678 9012",
                   "654321", "123456789012", "AB12345678"):
        assert secret not in safe
    assert "[email redacted]" in safe
    assert "[one-time password redacted]" in safe
    assert "[bank account redacted]" in safe
    assert "[exam identifier redacted]" in safe


def test_academic_marks_are_not_redacted():
    assert redact("Physics 45, Chemistry 65, Biology 72 and English 80") == (
        "Physics 45, Chemistry 65, Biology 72 and English 80"
    )
