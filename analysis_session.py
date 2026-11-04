"""Bounded memoization in the caller's private session; never a global holdings cache."""

import json
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from hashlib import sha256
from inspect import getsource

import numpy as np
import pandas as pd


def _serializable(value):
    if isinstance(value, (pd.DataFrame, pd.Series)):
        return {
            "data_sha256": sha256(pd.util.hash_pandas_object(value, index=True).values.tobytes()).hexdigest(),
            "columns": list(value.columns) if isinstance(value, pd.DataFrame) else [value.name],
            "dtypes": [str(item) for item in value.dtypes]
            if isinstance(value, pd.DataFrame)
            else str(value.dtype),
        }
    if isinstance(value, np.ndarray):
        return {
            "sha256": sha256(value.tobytes()).hexdigest(),
            "shape": value.shape,
            "dtype": str(value.dtype),
        }
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bytes):
        return {"sha256": sha256(value).hexdigest()}
    if is_dataclass(value):
        return asdict(value)
    raise TypeError("No se puede identificar esta configuración de análisis.")


def analysis_key(*values):
    return sha256(
        json.dumps(
            values, default=_serializable, sort_keys=True, allow_nan=False, ensure_ascii=False
        ).encode()
    ).hexdigest()


def session_compute(state, namespace, key, compute, *, max_entries=3):
    """Only successful computations are kept, copied so UI mutation cannot corrupt them."""
    storage_key = f"_analysis_memo_{namespace}"
    cache = dict(state.get(storage_key, {}))
    if key not in cache:
        value = compute()
        cache[key] = deepcopy(value)
        while len(cache) > max_entries:
            del cache[next(iter(cache))]
        state[storage_key] = cache
    return deepcopy(cache[key])


def session_call(state, function, *args, **kwargs):
    """Keep optional research results until their inputs or implementation change."""
    key = analysis_key(function.__module__, function.__qualname__, getsource(function), args, kwargs)
    return session_compute(
        state, "optional_" + function.__name__, key, lambda: function(*args, **kwargs), max_entries=12
    )
