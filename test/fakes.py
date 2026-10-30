"""Test doubles for the async-execution suite."""

from typing import Any, Callable, Mapping

from vre_rocrate import RuntimePlatform


class FakeAsyncIM:
    """Scripted AsyncIMProtocol double: canned state transitions, no network.

    Args:
        outputs: Returned by run()/resume() after the scripted states cycle.
        states: Sequence of states the wait loop observes before
            "configured"; a ``"failed"`` entry makes the wait raise IMError
            (with a matching destroy), an Exception entry is raised as-is.
    """

    def __init__(
        self,
        outputs: Mapping[str, Any] | None = None,
        states: list | None = None,
        destroy_raises: Exception | None = None,
    ):
        from app.exceptions import IMError

        self._IMError = IMError
        self._outputs = (
            dict(outputs) if outputs is not None else {"url": "https://vre.example"}
        )
        self._states = list(states) if states else []
        self._destroy_raises = destroy_raises
        self.inf_id: str | None = None
        self.created_with: list[RuntimePlatform] = []
        self.resumed_with: list[str] = []
        self.destroyed: list[str] = []
        self.heartbeats: list[str] = []
        self.closed = False

    async def _emit(self, heartbeat, stage: str) -> None:
        if heartbeat is not None:
            self.heartbeats.append(stage)
            result = heartbeat(stage)
            if hasattr(result, "__await__"):
                await result

    async def _wait(self, heartbeat) -> None:
        for state in self._states + ["configured"]:
            await self._emit(heartbeat, f"IM state: {state}")
            if isinstance(state, Exception):
                raise state
            if state == "failed":
                await self.destroy()
                raise self._IMError("Current state: failed")
            if state == "configured":
                return

    async def run(
        self,
        rp: RuntimePlatform,
        heartbeat: Callable | None = None,
        on_inf_created: Callable | None = None,
    ) -> Mapping[str, Any]:
        self.created_with.append(rp)
        self.inf_id = f"fake-inf-{len(self.created_with)}"
        if on_inf_created is not None:
            result = on_inf_created(self.inf_id)
            if hasattr(result, "__await__"):
                await result
        await self._wait(heartbeat)
        return self._outputs

    async def resume(
        self, inf_id: str, heartbeat: Callable | None = None
    ) -> Mapping[str, Any]:
        self.resumed_with.append(inf_id)
        self.inf_id = inf_id
        await self._wait(heartbeat)
        return self._outputs

    async def destroy(self, inf_id: str | None = None) -> None:
        inf_id = inf_id or self.inf_id
        if self._destroy_raises is not None:
            raise self._destroy_raises
        if inf_id is not None:
            self.destroyed.append(inf_id)
            if inf_id == self.inf_id:
                self.inf_id = None

    async def aclose(self) -> None:
        self.closed = True
