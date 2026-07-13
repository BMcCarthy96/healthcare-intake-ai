# Mock downstream export

A stdlib-only HTTP service that stands in for the downstream export system. It never accepts
real data.

`POST /exports` responds according to the `X-Mock-Export-Mode` request header:

| Mode | Response |
| --- | --- |
| `success` | `202 Accepted` |
| `timeout` | sleeps 3s, then `504` |
| `rate_limit` | `429` |
| `permanent_failure` | `422` |
| anything else | `400` |

The API selects the mode via the `MOCK_EXPORT_MODE` environment variable (default `success`)
and calls this service only when `MOCK_EXPORT_URL` is set — see `docker-compose.yml`.
