from baseline.baseline_engine import BaselineEngine


class BaselineRegistry:

    def __init__(
        self,
        alpha=0.1,
        window_size=120,
        min_samples=30
    ):
        self.alpha = alpha
        self.window_size = window_size
        self.min_samples = min_samples
        self.baselines = {}

    def checkpoint(self):
        return {
            key: baseline.checkpoint()
            for key, baseline in self.baselines.items()
        }

    def restore(self, snapshot):
        restored = {}
        for key, state in snapshot.items():
            baseline = BaselineEngine(
                alpha=state["alpha"],
                window_size=state["window_size"],
                min_samples=state["min_samples"],
            )
            baseline.restore(state)
            restored[key] = baseline
        self.baselines = restored

    def update(
        self,
        tenant_id,
        source_id,
        metric,
        value
    ):
        if not all(
            isinstance(item, str) and item.strip()
            for item in (tenant_id, source_id, metric)
        ):
            raise ValueError(
                "Tenant ID, source ID and metric are required"
            )

        key = (tenant_id, source_id, metric)

        if key not in self.baselines:
            self.baselines[key] = BaselineEngine(
                alpha=self.alpha,
                window_size=self.window_size,
                min_samples=self.min_samples
            )

        self.baselines[key].update(value)

    def get_baseline(
        self,
        tenant_id,
        source_id,
        metric
    ):
        if not all(
            isinstance(item, str) and item.strip()
            for item in (tenant_id, source_id, metric)
        ):
            raise ValueError(
                "Tenant ID, source ID and metric are required"
            )

        key = (tenant_id, source_id, metric)

        if key not in self.baselines:
            return None

        return self.baselines[key].get_baseline()
