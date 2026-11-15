"""Verified idle CUDA release; only scalar allocator diagnostics leave this worker."""
import gc

IDLE_RESERVED_MIB = 256
MIB = 1024**2


def allocator_state(torch, device):
    if not str(device).startswith("cuda") or not torch.cuda.is_initialized():
        return dict(allocated_mib=0, reserved_mib=0, active_mib=0, inactive_split_mib=0)
    stats = torch.cuda.memory_stats(device)
    return {
        name: round(stats.get(key, 0) / MIB, 1)
        for name, key in (
            ("allocated_mib", "allocated_bytes.all.current"),
            ("reserved_mib", "reserved_bytes.all.current"),
            ("active_mib", "active_bytes.all.current"),
            ("inactive_split_mib", "inactive_split_bytes.all.current"),
        )
    }


def release_idle_cuda(torch, device):
    gc.collect()
    initialized = str(device).startswith("cuda") and torch.cuda.is_initialized()
    if initialized:
        torch.cuda.synchronize(device)
        torch.cuda.empty_cache()
    before = allocator_state(torch, device)
    cleared_workspaces = False
    if initialized and before["reserved_mib"] > IDLE_RESERVED_MIB:
        # PyTorch 2.8 retains cuBLAS handle/stream workspaces across empty_cache.
        # Small workspace blocks can pin a much larger split model-load segment.
        clear = getattr(torch._C, "_cuda_clearCublasWorkspaces", None)
        if callable(clear):
            clear()
            cleared_workspaces = True
        gc.collect()
        torch.cuda.empty_cache()
    after = allocator_state(torch, device)
    return dict(
        confirmed=after["reserved_mib"] <= IDLE_RESERVED_MIB,
        idle_reserved_limit_mib=IDLE_RESERVED_MIB,
        cleared_cublas_workspaces=cleared_workspaces,
        before=before,
        after=after,
    )
