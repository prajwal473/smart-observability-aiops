"""Helpers for explicit component checkpoint and restore contracts."""

import threading


# Checkpoints can span collaborators shared by multiple engine instances.
# Acquire this before any component checkpoint or StateStore transaction.
ENGINE_TRANSACTION_LOCK = threading.RLock()


def checkpoint_component(component, component_name):
    """Capture an independent checkpoint from a transactional component."""

    checkpoint = getattr(component, "checkpoint", None)
    restore = getattr(component, "restore", None)

    declared = type(component).__dict__
    if (
        not callable(checkpoint)
        or not callable(restore)
        or not callable(declared.get("checkpoint"))
        or not callable(declared.get("restore"))
    ):
        raise TypeError(
            f"{component_name} must implement checkpoint() and restore() "
            "on its concrete class to participate in atomic batch processing"
        )

    try:
        state = checkpoint()
    except NotImplementedError as exc:
        raise TypeError(
            f"{component_name} does not support atomic batch processing"
        ) from exc

    return component, state, component_name


def restore_component(checkpoint_state):
    """Restore a component from its previously captured checkpoint."""

    component, state, component_name = checkpoint_state
    restore = getattr(component, "restore", None)

    if not callable(restore):
        raise TypeError(
            f"{component_name} no longer provides restore()"
        )

    restore(state)
