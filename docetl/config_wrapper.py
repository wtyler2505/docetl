import os
from docetl.console import get_console
from docetl.utils import load_config
from typing import Any, Dict, List, Optional, Tuple, Union
from docetl.operations.utils import APIWrapper
import pyrate_limiter
from inspect import isawaitable
import math


class BucketCollection(pyrate_limiter.BucketFactory):
    def __init__(self, **buckets):
        self.clock = pyrate_limiter.TimeClock()
        self.buckets = buckets

    def wrap_item(self, name: str, weight: int = 1) -> pyrate_limiter.RateItem:
        now = self.clock.now()

        async def wrap_async():
            return pyrate_limiter.RateItem(name, await now, weight=weight)

        def wrap_sync():
            return pyrate_limiter.RateItem(name, now, weight=weight)

        return wrap_async() if isawaitable(now) else wrap_sync()

    def get(self, item: pyrate_limiter.RateItem) -> pyrate_limiter.AbstractBucket:
        if item.name not in self.buckets:
            return self.buckets["unknown"]
        return self.buckets[item.name]


class ConfigWrapper(object):
    @classmethod
    def from_yaml(cls, yaml_file: str, **kwargs):
        config = load_config(yaml_file)
        return cls(config, **kwargs)

    def __init__(self, config: Dict, max_threads: int = None):
        self.config = config
        self.default_model = self.config.get("default_model", "gpt-4o-mini")

        # Reset the DOCETL_CONSOLE
        global DOCETL_CONSOLE
        DOCETL_CONSOLE = get_console()

        self.console = DOCETL_CONSOLE
        self.max_threads = max_threads or (os.cpu_count() or 1) * 4
        self.status = None

        buckets = {
            param: pyrate_limiter.InMemoryBucket(
                [
                    pyrate_limiter.Rate(
                        param_limit["count"],
                        param_limit["per"]
                        * getattr(
                            pyrate_limiter.Duration,
                            param_limit.get("unit", "SECOND").upper(),
                        ),
                    )
                    for param_limit in param_limits
                ]
            )
            for param, param_limits in self.config.get("rate_limits", {}).items()
        }
        buckets["unknown"] = pyrate_limiter.InMemoryBucket(
            [pyrate_limiter.Rate(math.inf, 1)]
        )
        bucket_factory = BucketCollection(**buckets)
        self.rate_limiter = pyrate_limiter.Limiter(bucket_factory, max_delay=math.inf)

        self.api = APIWrapper(self)
