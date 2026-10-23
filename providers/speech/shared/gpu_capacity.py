"""Bounded admission wait so another service's idle timer can release memory."""
import time


def wait_for_capacity(read_memory, minimum, timeout=360, clock=time.monotonic,
                      sleep=time.sleep, on_wait=lambda value: None):
    deadline = clock() + timeout
    try:
        while True:
            free, total = read_memory()
            if free >= minimum:
                return
            on_wait(True)
            if clock() >= deadline:
                raise RuntimeError(
                    f"GPU capacity temporarily unavailable: {free / 1024**3:.2f} GiB free of "
                    f"{total / 1024**3:.2f} GiB; requires {minimum / 1024**3:.2f} GiB"
                )
            sleep(min(2, max(0, deadline - clock())))
    finally:
        on_wait(False)
