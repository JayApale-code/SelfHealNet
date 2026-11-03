# API Documentation

## Dashboard data
- `GET /api/v1/incidents` and `GET /api/v1/predictions` return database-backed dashboard records.
- `GET /api/v1/metrics/live` returns fresh persisted telemetry; `GET /api/v1/metrics/history` returns recorded history.
- `GET /api/v1/recovery/status` returns the latest persisted recovery record and its attempts, or the current pending action if no recovery record exists.
- The dashboard WebSocket snapshot reads recovery status and live metrics from the same persisted sources.

## Diagnosis and recovery
- `POST /api/v1/diagnosis` records a diagnosed non-normal fault as an incident. It stores a supplied ML prediction only when both its label and probability are present and valid. A normal diagnosis does not create an incident.
- `POST /api/v1/recovery/workflow` records its incident, decision, safety result, verification, and recovery attempts. A workflow blocked before controller execution is recorded as a blocked attempt with no executed actions.

## Root endpoints
- `GET /health`
- `GET /api/v1/status` (reserved)

## Authentication
- `POST /api/v1/auth/register` accepts `full_name`, `username`, `email`, `mobile_number`, and `password`. The phone field is stored on the existing user record; account/profile responses return only a masked value.
- `POST /api/v1/auth/login` records successful sign-ins in `user_login_activity` and updates `last_login_at`. `GET /api/v1/users/login-history` returns the authenticated user's sign-in history.
- `POST /api/v1/auth/forgot-password` accepts an email and requests a five-minute OTP. Responses do not disclose whether the account exists. In development, the mock provider does not send SMS or expose the code; outside development, requests remain unavailable until a real provider is configured.
- `POST /api/v1/auth/verify-reset-otp` accepts `email` and a six-digit `otp`. Codes expire after five minutes and are locked after five failed attempts. A verified code is one-time and returns a short-lived reset token.
- `POST /api/v1/auth/reset-password` accepts the verified `token`, `new_password`, and `confirm_password`. The new password uses the existing PBKDF2-SHA256 password hash.

Reset-flow schema additions are applied additively when the backend initializes its database tables; existing password-reset rows are retained.
