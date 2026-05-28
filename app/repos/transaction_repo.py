from google.cloud import firestore


class TransactionRepo:
    def __init__(self, db: firestore.AsyncClient):
        self.db = db

    def _col(self, event_id: str):
        return (
            self.db.collection("saleEvents")
            .document(event_id)
            .collection("transactions")
        )

    async def add_transaction(self, event_id: str, tx_data: dict) -> str:
        ref = self._col(event_id).document()
        await ref.set({**tx_data, "createdAt": firestore.SERVER_TIMESTAMP})
        return ref.id

    async def list_transactions(self, event_id: str) -> list[dict]:
        docs = await (
            self._col(event_id).order_by("createdAt", direction="DESCENDING").get()
        )
        return [{**d.to_dict(), "id": d.id} for d in docs]
