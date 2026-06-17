from __future__ import annotations

from dataclasses import dataclass

from django.utils import timezone

from marketdata.models import StockDataCollectionStatus


@dataclass(frozen=True)
class CollectionStatusSnapshot:
    status: str
    source: str
    last_row_count: int
    last_message: str


def get_collection_status_snapshot(stock, data_type: str) -> CollectionStatusSnapshot:
    status = StockDataCollectionStatus.objects.filter(stock=stock, data_type=data_type).first()
    if status is None:
        return CollectionStatusSnapshot(
            status=StockDataCollectionStatus.STATUS_NEVER,
            source="",
            last_row_count=0,
            last_message="",
        )
    return CollectionStatusSnapshot(
        status=status.status,
        source=status.source,
        last_row_count=status.last_row_count,
        last_message=status.last_message,
    )


def record_collection_status(
    *,
    stock,
    data_type: str,
    status: str,
    source: str,
    row_count: int = 0,
    message: str = "",
):
    status_obj, _ = StockDataCollectionStatus.objects.get_or_create(
        stock=stock,
        data_type=data_type,
        defaults={
            "source": source,
            "status": status,
        },
    )
    status_obj.source = source
    status_obj.status = status
    status_obj.last_synced_at = timezone.now()
    status_obj.last_row_count = max(int(row_count), 0)
    status_obj.last_message = message.strip()
    if status in {StockDataCollectionStatus.STATUS_SUCCESS, StockDataCollectionStatus.STATUS_EMPTY}:
        status_obj.last_success_at = status_obj.last_synced_at
    status_obj.save(
        update_fields=[
            "source",
            "status",
            "last_synced_at",
            "last_success_at",
            "last_row_count",
            "last_message",
            "updated_at",
        ]
    )
    return status_obj
