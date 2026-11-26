"""The same external oracle is used before packaging and by the packaged replay."""
import sqlite3


def stored_deliveries(db):
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT id,lane,request,parcel FROM deliveries ORDER BY id").fetchall()
    finally:
        conn.close()


def check(factory, method, directory):
    db = directory / "desk.sqlite"
    request = ("lane-blue", "order-A", "paper kite")
    other = ("lane-gold", "order-B", "tin bird")
    ids = []
    # Reopen the service between submissions: retries must not add a delivery.
    for item in (request, other, request):
        desk = factory(db)
        try:
            ids.append(getattr(desk, method)(*item))
        finally:
            desk.db.close()
    receipts = stored_deliveries(db)
    if (ids[0] != ids[2] or ids[0] == ids[1] or
            receipts != [(ids[0], *request), (ids[1], *other)]):
        raise ValueError("returned IDs do not match independently stored deliveries")
    # The same order ID must not silently accept a different payload.
    desk = factory(db)
    try:
        try:
            getattr(desk, method)(request[0], request[1], "changed parcel")
        except ValueError:
            pass
        else:
            raise ValueError("request ID accepted with different contents")
    finally:
        desk.db.close()
    after = stored_deliveries(db)
    if after != receipts:
        raise ValueError("rejected request changed existing deliveries")
    return {"receipts": ids[:2], "delivery_count": len(receipts), "retry_receipt": ids[2]}
