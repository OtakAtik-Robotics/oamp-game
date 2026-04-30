import numpy as np
from sklearn.preprocessing import PolynomialFeatures
from sklearn.linear_model import LinearRegression

# ── Module-level singleton: train once, reuse forever ──────────────────────
_x_time = np.array([9, 10, 11, 12, 14, 16, 18, 20, 25, 30, 35, 40, 45, 50]).reshape(-1, 1)
_y_age  = np.array([20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85])

_poly  = PolynomialFeatures(degree=2)
_x_poly = _poly.fit_transform(_x_time)
_model  = LinearRegression()
_model.fit(_x_poly, _y_age)


def estimate_cognitive_age(time_finish_one_task: float) -> int:
    """
    Estimate cognitive age from a single block-arrangement completion time.
    Uses a pre-trained polynomial regression model (module singleton — no re-fitting).
    Returns age clamped to [20, 90].
    """
    inp = _poly.transform(np.array([[time_finish_one_task]]))
    age: float = _model.predict(inp)[0]

    if age < 20:
        age = 20
    elif age > 85:
        age = 90

    return int(age)