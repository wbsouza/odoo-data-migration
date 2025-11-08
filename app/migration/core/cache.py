import json
import os
import threading
from typing import Any, Callable, Dict,  Union


class CacheService:

    def __init__(self, fetch_fn: Callable[[str], Any]):
        self._cache: Dict[Union[int, str], Any] = {}
        self._fetch_fn = fetch_fn

    def set(self, _id: Union[int, str], data: Any) -> None:
        self._cache[_id] = data

    def get(
        self,
        _id: Union[int, str],
    ) -> Any:
        cached = self._cache.get(_id)
        if cached is not None:
            return cached
        # fetch single via batched API signature
        record = self._fetch_fn(_id) or None
        if record:
            self.set(_id, record)
        return record

