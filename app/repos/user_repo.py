from google.cloud import firestore


class UserRepo:
    def __init__(self, db: firestore.AsyncClient):
        self.db = db

    async def upsert_user(self, user_id: str, email: str, name: str | None = None) -> None:
        await self.db.collection("users").document(user_id).set(
            {
                "email": email,
                "displayName": name,
                "lastLogin": firestore.SERVER_TIMESTAMP,
                "updatedAt": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )
