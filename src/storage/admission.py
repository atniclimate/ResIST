"""Apply the pool admission snapshot before a local reader selects, counts or pages results."""
import json

from resist.services.policy import readable_resolution_ids


def admitted_ids(connection):
    raw = connection.connection.driver_connection
    # sqlite3's legacy transaction mode does not start a transaction for SELECT.
    if not raw.in_transaction:
        raw.execute("BEGIN")
    return readable_resolution_ids(raw)


def admitted_params(connection):
    return {"admitted": json.dumps(admitted_ids(connection))}


ADMITTED = "SELECT value FROM json_each(:admitted)"
