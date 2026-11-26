"""Invented editions of a parcel desk. Only this service writes delivery receipts."""
import sqlite3


class Desk:
    def __init__(self, database):
        self.db = sqlite3.connect(database)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS deliveries (
                id INTEGER PRIMARY KEY, lane TEXT, request TEXT UNIQUE, parcel TEXT
            )
        """)

    def _deliver(self, lane, request, parcel):
        with self.db:
            self.db.execute("INSERT INTO deliveries(lane,request,parcel) VALUES (?,?,?) "
                            "ON CONFLICT(request) DO NOTHING", (lane, request, parcel))
            rid, old_lane, old_parcel = self.db.execute(
                "SELECT id,lane,parcel FROM deliveries WHERE request=?", (request,)
            ).fetchone()
            if (old_lane, old_parcel) != (lane, parcel):
                raise ValueError("request reused with different contents")
        return rid


class DeskV1(Desk):
    def dispatch(self, lane, request, parcel):
        return self._deliver(lane, request, parcel)


class DeskV2(Desk):
    def dispatch_preview(self, lane, request, parcel):
        return 1  # A plausible ID is not a receipt.

    def dispatch_redirect(self, lane, request, parcel):
        return self._deliver("other-lane", request, parcel)

    def dispatch_v2(self, lane, request, parcel):
        return self._deliver(lane, request, parcel)


class DeskV3(Desk):
    dispatch_preview = DeskV2.dispatch_preview
    dispatch_redirect = DeskV2.dispatch_redirect

    def dispatch_v2(self, contents, /, order_id, *, chute):
        return self._deliver(chute, order_id, contents)
