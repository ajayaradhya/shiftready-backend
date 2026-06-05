import logging

import httpx

logger = logging.getLogger(__name__)

_EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


class PushService:
    """Fan-out push notifications via Expo Push API."""

    def __init__(self, user_repo):
        self.user_repo = user_repo

    async def notify(
        self,
        uid: str,
        title: str,
        body: str,
        data: dict | None = None,
    ) -> None:
        try:
            tokens = await self.user_repo.get_push_tokens(uid)
            if not tokens:
                return
            await _send_expo_push(tokens, title, body, data or {})
        except Exception as exc:
            logger.warning("Push fan-out failed for uid %s: %s", uid, exc)


async def _send_expo_push(
    tokens: list[str],
    title: str,
    body: str,
    data: dict,
) -> None:
    valid = [t for t in tokens if t.startswith("ExponentPushToken[")]
    if not valid:
        return
    messages = [
        {"to": token, "sound": "default", "title": title, "body": body, "data": data}
        for token in valid
    ]
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            _EXPO_PUSH_URL,
            json=messages,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip, deflate",
                "Content-Type": "application/json",
            },
        )
        if resp.status_code >= 400:
            logger.warning("Expo Push API returned %d: %s", resp.status_code, resp.text)
