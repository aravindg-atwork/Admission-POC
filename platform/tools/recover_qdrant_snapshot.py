"""Recover a named Qdrant collection from a snapshot visible to Qdrant."""

import sys

from qdrant_client import QdrantClient
from qdrant_client.models import SnapshotPriority


if len(sys.argv) != 3:
    raise SystemExit("usage: recover_qdrant_snapshot.py <collection> <snapshot-location>")

client = QdrantClient(url="http://qdrant:6333")
client.recover_snapshot(
    collection_name=sys.argv[1],
    location=sys.argv[2],
    priority=SnapshotPriority.SNAPSHOT,
    wait=True,
)
print(f"recovered {sys.argv[1]}: {client.count(sys.argv[1], exact=True).count} points")
