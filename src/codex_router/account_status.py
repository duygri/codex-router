"""Safe Codex account status derived from Codex App Server."""

import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class AccountStatus:
  state: str
  auth_mode: Optional[str] = None
  message: str = ""
class AccountStatusProbe:
  """Cache-backed probe for Codex account status."""

  def __init__(
    self,
    probe,
    cache_ttl=10.0,
    clock=None,
  ):
    self.probe = probe
    self.cache_ttl = max(0.0, float(cache_ttl))
    self.clock = clock or time.monotonic
    self.lock = threading.Lock()
    self.cached_status = None
    self.cached_at = None
  def check(self):
    with self.lock:
      now = self.clock()
  
    if (
      self.cached_status is not None
      and self.cached_at is not None
      and now - self.cached_at < self.cache_ttl
    ):
      return self.cached_status
      try:
        status = self.probe()
      except Exception:
        status = AccountStatus(
          state="unavailable",
          message="Codex account status is unavailable",
        )
      self.cached_status = status
      self.cached_at = self.clock()
      return status
  
  with self.lock:
    now = self.clock()

if (
  
