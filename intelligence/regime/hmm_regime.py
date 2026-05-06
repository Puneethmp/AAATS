"""
Hidden Markov Model Regime Detection
======================================
Why this exists
---------------
The existing `indicators/regime_detector.py` uses rule-based heuristics
(EMA spread + ADX + ATR). That works but it is reactive — it identifies
a regime change AFTER the price has moved. HMMs are generative: they
infer the hidden state driving the observed returns, and can do so with
a probabilistic confidence estimate at each bar.

HMMs are used by Two Sigma, DE Shaw, and most systematic macro funds for
regime-switching strategy allocation.

Architecture
------------
We implement a Gaussian HMM (without external hmmlearn dependency):
  - Observations: [return, log_volatility, volume_z] (3D)
  - Hidden states: 2 (bear/bull) or 3 (bear/sideways/bull)
  - Emission: multivariate Gaussian
  - Training: Baum-Welch EM algorithm (forward-backward)
  - Decoding: Viterbi algorithm

Outputs
-------
  - regime_probs: probability of each state at each timestep (soft assignment)
  - regime: most likely state at each timestep (hard Viterbi assignment)
  - regime_label: 'bull', 'bear', or 'sideways' (inferred from state stats)

Usage
-----
  from intelligence.regime.hmm_regime import GaussianHMM

  hmm = GaussianHMM(n_states=2, n_iter=100, random_state=42)
  hmm.fit(df)                         # df must have: close, volume (optional)
  probs = hmm.predict_proba(df)       # DataFrame of state probabilities
  states = hmm.predict(df)            # Series of regime labels
  report = hmm.regime_report(df)      # Summary statistics per regime
"""

from __future__ import annotations

import warnings
from typing import Literal

import numpy as np
import pandas as pd

__all__ = ["GaussianHMM"]

_EPS = 1e-300  # prevent log(0)


# ---------------------------------------------------------------------------
# Gaussian HMM
# ---------------------------------------------------------------------------
class GaussianHMM:
    """
    Gaussian Hidden Markov Model for regime detection.

    Parameters
    ----------
    n_states      Number of hidden states (2 = bear/bull, 3 = bear/sideways/bull).
    n_iter        Maximum EM iterations.
    tol           Convergence tolerance on log-likelihood improvement.
    random_state  Random seed for reproducible initialisation.
    min_covar     Minimum variance to prevent degenerate covariance matrices.
    """

    def __init__(
        self,
        n_states: int = 2,
        n_iter: int = 100,
        tol: float = 1e-4,
        random_state: int = 42,
        min_covar: float = 1e-6,
    ):
        if n_states not in (2, 3):
            raise ValueError("n_states must be 2 or 3.")
        self.n_states = n_states
        self.n_iter = n_iter
        self.tol = tol
        self.random_state = random_state
        self.min_covar = min_covar
        self._fitted = False

        # Model parameters (initialised in fit())
        self.pi_: np.ndarray | None = None        # initial state probs (K,)
        self.A_: np.ndarray | None = None         # transition matrix (K, K)
        self.mu_: np.ndarray | None = None        # emission means (K, D)
        self.sigma_: np.ndarray | None = None     # emission covariances (K, D, D)
        self._state_labels: list[str] = []
        self._log_likelihood_: float = float("-inf")

    # ------------------------------------------------------------------
    # Feature extraction
    # ------------------------------------------------------------------
    def _extract_features(self, df: pd.DataFrame) -> np.ndarray:
        """
        Extract a (T, D) observation matrix from a price DataFrame.

        Features:
          0: daily return (normalised)
          1: log realised volatility (20-bar rolling)
          2: volume z-score (if available, else 0)
        """
        close = df["close"].replace(0, np.nan).ffill()
        ret = close.pct_change().fillna(0).values

        # Realised volatility (log, rolling 20-bar std of returns)
        rv = pd.Series(ret).rolling(20, min_periods=5).std().fillna(
            pd.Series(ret).std()
        ).values
        log_rv = np.log(np.maximum(rv, 1e-8))

        # Volume z-score
        if "volume" in df.columns and (df["volume"] > 0).any():
            vol = df["volume"].fillna(0).values.astype(float)
            vol_mean = vol.mean()
            vol_std = vol.std()
            vol_z = (vol - vol_mean) / max(vol_std, 1e-8)
        else:
            vol_z = np.zeros(len(ret))

        X = np.column_stack([ret, log_rv, vol_z])
        return X.astype(float)

    # ------------------------------------------------------------------
    # Gaussian emission log-probability
    # ------------------------------------------------------------------
    def _log_emission(self, X: np.ndarray) -> np.ndarray:
        """
        Compute log P(x_t | state k) for all t and k.

        Returns (T, K) matrix.
        """
        T, D = X.shape
        K = self.n_states
        log_p = np.zeros((T, K))
        for k in range(K):
            diff = X - self.mu_[k]  # (T, D)
            sigma = self.sigma_[k]  # (D, D)
            sign, logdet = np.linalg.slogdet(sigma)
            if sign <= 0:
                logdet = 0.0
            try:
                sigma_inv = np.linalg.inv(sigma)
            except np.linalg.LinAlgError:
                sigma_inv = np.linalg.pinv(sigma)
            mahal = np.einsum("ti,ij,tj->t", diff, sigma_inv, diff)
            log_p[:, k] = -0.5 * (D * np.log(2 * np.pi) + logdet + mahal)
        return log_p

    # ------------------------------------------------------------------
    # Forward algorithm
    # ------------------------------------------------------------------
    def _forward(self, log_p: np.ndarray) -> tuple[np.ndarray, float]:
        """
        Forward algorithm in log-space for numerical stability.

        Returns (alpha, log_likelihood) where alpha is (T, K) log-scale.
        """
        T, K = log_p.shape
        log_alpha = np.full((T, K), -np.inf)
        log_alpha[0] = np.log(self.pi_ + _EPS) + log_p[0]

        for t in range(1, T):
            for k in range(K):
                # log Σ_j [alpha_{t-1,j} * A_{j,k}]
                vals = log_alpha[t - 1] + np.log(self.A_[:, k] + _EPS)
                log_alpha[t, k] = self._logsumexp(vals) + log_p[t, k]

        log_lik = self._logsumexp(log_alpha[-1])
        return log_alpha, log_lik

    # ------------------------------------------------------------------
    # Backward algorithm
    # ------------------------------------------------------------------
    def _backward(self, log_p: np.ndarray) -> np.ndarray:
        T, K = log_p.shape
        log_beta = np.zeros((T, K))  # log(1) = 0 at T-1
        for t in range(T - 2, -1, -1):
            for k in range(K):
                vals = np.log(self.A_[k, :] + _EPS) + log_p[t + 1] + log_beta[t + 1]
                log_beta[t, k] = self._logsumexp(vals)
        return log_beta

    # ------------------------------------------------------------------
    # Baum-Welch EM
    # ------------------------------------------------------------------
    def fit(self, df: pd.DataFrame) -> "GaussianHMM":
        """
        Fit the HMM using Baum-Welch (EM) on the price DataFrame.

        Parameters
        ----------
        df    DataFrame with at minimum a 'close' column.
        """
        X = self._extract_features(df)
        T, D = X.shape
        K = self.n_states
        rng = np.random.default_rng(self.random_state)

        # Initialise parameters via k-means-like assignment
        self.pi_ = np.ones(K) / K
        self.A_ = (np.ones((K, K)) * 0.1 + np.eye(K) * (K - 1)) / K
        self.mu_ = X[rng.choice(T, K, replace=False)]
        self.sigma_ = np.array([np.eye(D) * X.var(axis=0).mean() for _ in range(K)])

        prev_log_lik = float("-inf")

        for iteration in range(self.n_iter):
            # ---- E step ----
            log_p = self._log_emission(X)
            log_alpha, log_lik = self._forward(log_p)
            log_beta = self._backward(log_p)

            # Posterior state probabilities (gamma)
            log_gamma = log_alpha + log_beta  # (T, K)
            log_gamma -= self._logsumexp(log_gamma, axis=1, keepdims=True)
            gamma = np.exp(log_gamma)

            # Posterior pairwise state probabilities (xi)
            # xi[t, j, k] = P(s_t=j, s_{t+1}=k | X)
            xi = np.zeros((T - 1, K, K))
            for t in range(T - 1):
                for j in range(K):
                    for k in range(K):
                        xi[t, j, k] = (
                            log_alpha[t, j] +
                            np.log(self.A_[j, k] + _EPS) +
                            log_p[t + 1, k] +
                            log_beta[t + 1, k]
                        )
                # Normalise
                xi_t_max = xi[t].max()
                xi[t] = np.exp(xi[t] - xi_t_max)
                xi[t] /= max(xi[t].sum(), _EPS)

            # ---- M step ----
            # Initial state
            self.pi_ = np.maximum(gamma[0], _EPS)
            self.pi_ /= self.pi_.sum()

            # Transition matrix
            xi_sum = xi.sum(axis=0)  # (K, K)
            self.A_ = xi_sum / np.maximum(xi_sum.sum(axis=1, keepdims=True), _EPS)

            # Emission parameters
            gamma_sum = gamma.sum(axis=0)  # (K,)
            for k in range(K):
                gk = gamma[:, k]
                gk_sum = max(gamma_sum[k], _EPS)
                # Mean
                self.mu_[k] = (gk[:, None] * X).sum(axis=0) / gk_sum
                # Covariance
                diff = X - self.mu_[k]
                cov_k = (gk[:, None] * diff).T @ diff / gk_sum
                cov_k += np.eye(D) * self.min_covar
                self.sigma_[k] = cov_k

            # Convergence check
            improvement = log_lik - prev_log_lik
            if 0 < improvement < self.tol:
                break
            prev_log_lik = log_lik

        self._log_likelihood_ = float(log_lik)
        self._fitted = True
        self._assign_labels()
        return self

    # ------------------------------------------------------------------
    # Label assignment (bull / bear / sideways)
    # ------------------------------------------------------------------
    def _assign_labels(self):
        """Assign bull/bear/sideways labels based on state mean returns."""
        mean_rets = self.mu_[:, 0]  # first feature = return
        order = np.argsort(mean_rets)
        if self.n_states == 2:
            labels = ["bear", "bull"]
        else:
            labels = ["bear", "sideways", "bull"]
        self._state_labels = [""] * self.n_states
        for rank, state_idx in enumerate(order):
            self._state_labels[state_idx] = labels[rank]

    # ------------------------------------------------------------------
    # Viterbi decoding
    # ------------------------------------------------------------------
    def _viterbi(self, X: np.ndarray) -> np.ndarray:
        T, D = X.shape
        K = self.n_states
        log_p = self._log_emission(X)
        log_delta = np.full((T, K), -np.inf)
        psi = np.zeros((T, K), dtype=int)

        log_delta[0] = np.log(self.pi_ + _EPS) + log_p[0]

        for t in range(1, T):
            for k in range(K):
                vals = log_delta[t - 1] + np.log(self.A_[:, k] + _EPS)
                psi[t, k] = np.argmax(vals)
                log_delta[t, k] = vals[psi[t, k]] + log_p[t, k]

        # Backtrack
        states = np.zeros(T, dtype=int)
        states[-1] = np.argmax(log_delta[-1])
        for t in range(T - 2, -1, -1):
            states[t] = psi[t + 1, states[t + 1]]
        return states

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------
    def predict_proba(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Return soft state probabilities (T, K) DataFrame.

        Columns are the state labels ('bull', 'bear', 'sideways').
        """
        self._assert_fitted()
        X = self._extract_features(df)
        log_p = self._log_emission(X)
        log_alpha, _ = self._forward(log_p)
        log_beta = self._backward(log_p)
        log_gamma = log_alpha + log_beta
        log_gamma -= self._logsumexp(log_gamma, axis=1, keepdims=True)
        gamma = np.exp(log_gamma)
        cols = self._state_labels
        return pd.DataFrame(gamma, index=df.index, columns=cols)

    def predict(self, df: pd.DataFrame) -> pd.Series:
        """
        Return the most likely regime label at each timestep (Viterbi).

        Returns a Series with values in {'bull', 'bear', 'sideways'}.
        """
        self._assert_fitted()
        X = self._extract_features(df)
        states = self._viterbi(X)
        labels = [self._state_labels[s] for s in states]
        return pd.Series(labels, index=df.index, name="regime")

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------
    def regime_report(self, df: pd.DataFrame) -> dict:
        """
        Compute per-regime statistics: frequency, mean return, volatility,
        mean duration, and transition matrix.
        """
        self._assert_fitted()
        regimes = self.predict(df)
        close = df["close"].replace(0, np.nan).ffill()
        ret = close.pct_change().fillna(0)

        report: dict = {"regime_stats": {}, "transition_matrix": {}}

        for label in set(self._state_labels):
            mask = regimes == label
            r_regime = ret[mask]
            freq = mask.mean()
            # Duration: count consecutive runs
            runs = []
            run = 0
            for v in mask:
                if v:
                    run += 1
                else:
                    if run > 0:
                        runs.append(run)
                    run = 0
            if run > 0:
                runs.append(run)
            report["regime_stats"][label] = {
                "frequency_pct": round(float(freq * 100), 2),
                "mean_return_pct": round(float(r_regime.mean() * 100), 4),
                "ann_volatility_pct": round(float(r_regime.std() * np.sqrt(252) * 100), 3),
                "mean_duration_bars": round(float(np.mean(runs)), 1) if runs else 0,
                "n_episodes": len(runs),
            }

        # Transition matrix from A_
        for i, from_label in enumerate(self._state_labels):
            report["transition_matrix"][from_label] = {
                self._state_labels[j]: round(float(self.A_[i, j]), 4)
                for j in range(self.n_states)
            }

        report["log_likelihood"] = round(self._log_likelihood_, 3)
        report["n_states"] = self.n_states
        return report

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _assert_fitted(self):
        if not self._fitted:
            raise RuntimeError("Call fit() before predict(). Model not yet trained.")

    @staticmethod
    def _logsumexp(a: np.ndarray, axis: int | None = None, keepdims: bool = False) -> np.ndarray | float:
        if axis is None:
            a_max = np.max(a)
            result = np.log(np.sum(np.exp(a - a_max)) + _EPS) + a_max
            return float(result)
        a_max = np.max(a, axis=axis, keepdims=True)
        result = np.log(np.sum(np.exp(a - a_max), axis=axis, keepdims=True) + _EPS) + a_max
        if not keepdims:
            result = result.squeeze(axis=axis)
        return result
