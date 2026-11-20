from datetime import datetime, timezone


class EventCorrelator:
    """
    Groups related anomaly events by time window and source.
    """

    def __init__(self, time_window_seconds: int = 300):
        self.time_window_seconds = time_window_seconds

    def correlate(self, anomalies: list):
        if not anomalies:
            return []

        events = sorted(
            anomalies,
            key=lambda event: event.get("timestamp", ""),
        )

        groups = []
        current_group = [events[0]]

        for event in events[1:]:
            previous = current_group[-1]

            current_time = self._parse_time(event.get("timestamp"))
            previous_time = self._parse_time(previous.get("timestamp"))

            difference = (current_time - previous_time).total_seconds()

            same_source = (
                event.get("source_id") == previous.get("source_id")
            )

            if difference <= self.time_window_seconds and (
                same_source or difference <= 60
            ):
                current_group.append(event)
            else:
                groups.append(current_group)
                current_group = [event]

        groups.append(current_group)

        return [
            self._build_group(group)
            for group in groups
        ]

    @staticmethod
    def _parse_time(timestamp):
        if isinstance(timestamp, datetime):
            dt = timestamp
        else:
            dt = datetime.fromisoformat(
                timestamp.replace("Z", "+00:00")
            )

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt

    @staticmethod
    def _build_group(events):
        source_ids = sorted(
            set(event.get("source_id", "unknown") for event in events)
        )

        metrics = sorted(
            set(event.get("metric_name", "unknown") for event in events)
        )

        return {
            "event_count": len(events),
            "source_ids": source_ids,
            "metrics": metrics,
            "events": events,
            "start_time": events[0].get("timestamp"),
            "end_time": events[-1].get("timestamp"),
        }