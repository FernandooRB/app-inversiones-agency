"""One explicit covariance convention shared by interactive and snapshot analyses."""

from dataclasses import dataclass

import pandas as pd

from covariance_calibration import select_diagonal_shrinkage
from portfolio_core import PortfolioError, annualized_moments

METHOD_LABELS = {
    "calibrated": "Covarianza con contracción diagonal calibrada",
    "sample": "Covarianza muestral",
    "diagonal_50": "Contracción diagonal 50%",
}
DEFAULT_METHOD = "calibrated"


@dataclass(frozen=True)
class MomentEstimate:
    mean: pd.Series
    covariance: pd.DataFrame
    method: str
    shrinkage: float

    @property
    def description(self):
        return f"{METHOD_LABELS[self.method]} · intensidad {self.shrinkage:.0%}"


def estimate_moments(returns, method=DEFAULT_METHOD):
    if method not in METHOD_LABELS:
        raise PortfolioError("Elige un estimador de covarianza reconocido.")
    intensity = {"sample": 0.0, "diagonal_50": 0.5}.get(method)
    if method == "calibrated":
        if len(returns) < 100:
            raise PortfolioError(
                "La contracción calibrada requiere 100 retornos. Amplía la historia o elige "
                "explícitamente covarianza muestral/contracción 50%."
            )
        intensity = select_diagonal_shrinkage(returns).intensity
    mean, covariance = annualized_moments(returns, covariance_shrinkage=intensity)
    return MomentEstimate(mean, covariance, method, intensity)
