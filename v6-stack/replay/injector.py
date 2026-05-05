"""κ2 injector — block network egress + seed RNG inside the replay context.

Context manager. install() / uninstall() reverse cleanly. Every monkey-patch
registers its undo hook on the ExitStack BEFORE mutating, so a failure during
install fully unwinds — caller never observes a half-installed state.

What it patches (fail-closed; any unexpected call → RuntimeError):
  - random.seed(42)              deterministic RNG inside replay
  - socket.socket.connect        catches every TCP/UDP egress, including
                                 transports that bypass `requests` (urllib,
                                 httpx, aiohttp, raw sockets, ccxt's session)
  - socket.create_connection     same, for the convenience entry point
  - requests.adapters.HTTPAdapter.send   covers any requests.Session.* path
  - requests.get / requests.post belt-and-braces above the adapter layer
  - ccxt.base.exchange.Exchange.request  covers all CCXT REST methods
  - ccxt.async_support.base.exchange.Exchange.request  async variant
  - urllib.request.urlopen       stdlib egress
  - markets.crypto.fetcher.fetch_ohlcv  v5 entry point; bars come from tape
  - AAATS_DATA env var → tempfile.mkdtemp() dir; cleaned on exit

Loopback (127.0.0.1, ::1, localhost) is BLOCKED too — κ2 has no legitimate
local-network consumer (SQLite is file-backed, not socket-backed). If a
future κ phase needs loopback, relax in `_socket_guard` explicitly.

What it does NOT patch (yet):
  - datetime.now / time.time. v5 modules touched in κ2 §8.1 don't read these
    on the signal-generation hot path (verified during κ1 inventory). If §8.4
    replay shows wall-clock leakage, we extend the patch list and re-capture.
  - socket.socket.connect_ex (non-raising variant) and
    asyncio.open_connection / loop.create_connection. Catalogued in
    K2_REPLAY_NOTES.md §"Sources NOT yet exercised".
"""

from __future__ import annotations

import logging
import os
import random
import shutil
import socket
import tempfile
from contextlib import ExitStack, contextmanager
from typing import Iterator
from unittest.mock import patch

LOG = logging.getLogger("replay.injector")

REPLAY_SEED = 42


def _socket_guard(*_a, **_kw):
    raise RuntimeError("replay: socket egress blocked (no network in replay)")


@contextmanager
def install(seed: int = REPLAY_SEED) -> Iterator[None]:
    stack = ExitStack()
    try:
        # --- 1. RNG: register undo BEFORE mutating ---
        old_random_state = random.getstate()
        stack.callback(random.setstate, old_random_state)
        random.seed(seed)

        # --- 2. AAATS_DATA env var → isolated tempdir; cleaned on exit ---
        old_aaats_data = os.environ.get("AAATS_DATA")
        tmp_data_dir = tempfile.mkdtemp(prefix="aaats-replay-")

        def _restore_env_and_cleanup():
            if old_aaats_data is None:
                os.environ.pop("AAATS_DATA", None)
            else:
                os.environ["AAATS_DATA"] = old_aaats_data
            shutil.rmtree(tmp_data_dir, ignore_errors=True)

        stack.callback(_restore_env_and_cleanup)
        os.environ["AAATS_DATA"] = tmp_data_dir

        # --- 3. Socket-level kill switch (catches every network library) ---
        orig_connect = socket.socket.connect
        orig_create_connection = socket.create_connection

        def _restore_sockets():
            socket.socket.connect = orig_connect
            socket.create_connection = orig_create_connection

        stack.callback(_restore_sockets)
        socket.socket.connect = _socket_guard
        socket.create_connection = _socket_guard

        # --- 4. requests: belt-and-braces above socket layer (clearer errors) ---
        stack.enter_context(patch(
            "requests.adapters.HTTPAdapter.send",
            side_effect=RuntimeError("replay: requests HTTPAdapter.send blocked"),
        ))
        stack.enter_context(patch(
            "requests.get",
            side_effect=RuntimeError("replay: requests.get blocked"),
        ))
        stack.enter_context(patch(
            "requests.post",
            side_effect=RuntimeError("replay: requests.post blocked"),
        ))

        # --- 5. urllib stdlib egress ---
        stack.enter_context(patch(
            "urllib.request.urlopen",
            side_effect=RuntimeError("replay: urllib.request.urlopen blocked"),
        ))

        # --- 6. CCXT (sync + async). Skip if not installed. ---
        for target in (
            "ccxt.base.exchange.Exchange.request",
            "ccxt.async_support.base.exchange.Exchange.request",
        ):
            try:
                stack.enter_context(patch(
                    target,
                    side_effect=RuntimeError(f"replay: {target} blocked"),
                ))
            except (ImportError, AttributeError, ModuleNotFoundError) as e:
                LOG.debug("ccxt patch %s skipped: %s", target, e)

        # --- 7. v5 fetch_ohlcv: only patch if module imports cleanly ---
        try:
            stack.enter_context(patch(
                "markets.crypto.fetcher.fetch_ohlcv",
                side_effect=RuntimeError(
                    "replay: markets.crypto.fetcher.fetch_ohlcv blocked; "
                    "the runner provides bars from tape directly"
                ),
            ))
        except (ImportError, AttributeError, ModuleNotFoundError) as e:
            LOG.debug("fetch_ohlcv not patched: %s", e)

        yield
    finally:
        stack.close()
