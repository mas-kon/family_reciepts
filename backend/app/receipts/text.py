import difflib
import re
import unicodedata

from app.db.models import Category

_NON_WORD = re.compile(r"[^\w%]+", re.UNICODE)
_SPACES = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Key for grouping the same product across receipts: lowercase, no punctuation."""
    s = unicodedata.normalize("NFKC", name or "").lower().replace("ё", "е")
    s = _NON_WORD.sub(" ", s)
    s = s.replace("_", " ")
    return _SPACES.sub(" ", s).strip()


def category_path(cat: Category, by_id: dict[int, Category]) -> str:
    if cat.parent_id and cat.parent_id in by_id:
        return f"{by_id[cat.parent_id].name} / {cat.name}"
    return cat.name


def leaf_categories(categories: list[Category]) -> dict[str, Category]:
    """Map "Parent / Child" path -> category, only for categories without children."""
    by_id = {c.id: c for c in categories}
    parents = {c.parent_id for c in categories if c.parent_id}
    return {
        category_path(c, by_id): c
        for c in sorted(categories, key=lambda c: (c.parent_id or c.id, c.sort_order, c.id))
        if c.id not in parents
    }


class CategoryMatcher:
    """Turns free-form category text returned by the LLM into a category id."""

    def __init__(self, categories: list[Category], fallback_name: str = "Прочее"):
        self.paths = leaf_categories(categories)
        self._lower = {normalize_name(p): c for p, c in self.paths.items()}
        # also allow matching by the leaf name alone
        for path, c in self.paths.items():
            self._lower.setdefault(normalize_name(path.split(" / ")[-1]), c)
        self.fallback = next(
            (c for c in categories if c.name == fallback_name and not c.parent_id), None
        )

    def path_list(self) -> list[str]:
        return list(self.paths)

    def match(self, text: str | None) -> Category | None:
        if not text:
            return self.fallback
        key = normalize_name(text)
        if key in self._lower:
            return self._lower[key]
        close = difflib.get_close_matches(key, list(self._lower), n=1, cutoff=0.6)
        if close:
            return self._lower[close[0]]
        return self.fallback
