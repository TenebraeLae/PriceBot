from collections import OrderedDict


class RecentIdSet:
    def __init__(self, limit: int = 2000) -> None:
        self._limit = limit
        self._items: OrderedDict[str, None] = OrderedDict()

    def add_new(self, key: str) -> bool:
        if key in self._items:
            return False
        self._items[key] = None
        while len(self._items) > self._limit:
            self._items.popitem(last=False)
        return True


SEEN_UPDATES = RecentIdSet()
SEEN_IMPORTS = RecentIdSet()
