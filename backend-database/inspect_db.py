import sqlite3

connection = sqlite3.connect("local.db")

duplicates = connection.execute(
    """
    SELECT payload_id, COUNT(*)
    FROM telemetry_events
    GROUP BY payload_id
    HAVING COUNT(*) > 1
    """
).fetchall()

if duplicates:
    print("Duplicate payload IDs found:")
    for duplicate in duplicates:
        print(duplicate)
else:
    print("SUCCESS: No duplicate payload IDs found.")

connection.close()