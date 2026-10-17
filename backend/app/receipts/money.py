"""All amounts in the app are in euro."""


def round2(x: float | None) -> float | None:
    return None if x is None else round(x + 0.0, 2)
