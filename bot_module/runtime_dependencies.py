from typing import Any, Callable, Optional


class DependencyProxy:
    def __init__(self, name: str):
        self._name = name
        self._target: Optional[Any] = None
        self._overrides: dict[str, Any] = {}

    def configure(self, target: Any) -> None:
        self._target = target

    def __bool__(self) -> bool:
        return self._target is not None or bool(self._overrides)

    def __getattr__(self, name: str) -> Any:
        if name in self._overrides:
            return self._overrides[name]
        if self._target is None:
            raise RuntimeError(
                f"Runtime dependency '{self._name}' is not configured. "
                "Configure bot_module.runtime_dependencies from the process entrypoint."
            )
        return getattr(self._target, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        if self._target is None:
            self._overrides[name] = value
            return
        setattr(self._target, name, value)

    def __delattr__(self, name: str) -> None:
        if name in self._overrides:
            del self._overrides[name]
            return
        if self._target is None:
            raise AttributeError(name)
        delattr(self._target, name)


class CallableDependency:
    def __init__(self, name: str):
        self._name = name
        self._target: Optional[Callable[..., Any]] = None

    def configure(self, target: Callable[..., Any]) -> None:
        self._target = target

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if self._target is None:
            raise RuntimeError(
                f"Runtime dependency '{self._name}' is not configured. "
                "Configure bot_module.runtime_dependencies from the process entrypoint."
            )
        return self._target(*args, **kwargs)


crud = DependencyProxy("crud")
get_db = CallableDependency("get_db")
send_push_notification = CallableDependency("send_push_notification")


def configure_runtime_dependencies(
    *,
    crud_module: Any,
    get_db_factory: Callable[..., Any],
    push_sender: Callable[..., Any],
) -> None:
    crud.configure(crud_module)
    get_db.configure(get_db_factory)
    send_push_notification.configure(push_sender)
