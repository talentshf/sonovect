"""Local GPU memory measurement and PyTorch allocator limit."""
import time

class GPUStage:
    def __init__(self, consumer, budget_mib, reserve_mib=1024):
        if not 0 < budget_mib <= 1048576 or reserve_mib < 512:
            raise ValueError("audio_stage_budget_out_of_range")
        self.consumer, self.budget_mib = consumer, budget_mib
        self.reserve_mib = reserve_mib
        self.last = None
        self._started = None

    def configure(self, torch, device):
        if str(device).startswith("cuda") and torch.cuda.is_available():
            _, total = torch.cuda.mem_get_info(device)
            if (self.budget_mib + self.reserve_mib) * 1024**2 > total:
                raise RuntimeError("gpu_budget_exceeds_device_with_reserve")
            torch.cuda.set_per_process_memory_fraction(self.budget_mib * 1024**2 / total, device)

    def begin(self, torch, device):
        if str(device).startswith("cuda") and torch.cuda.is_available():
            self.configure(torch, device)
            torch.cuda.reset_peak_memory_stats(device)
            free, total = torch.cuda.mem_get_info(device)
            self._started = (time.monotonic(), free, total)

    def finish(self, torch, device):
        if self._started is None:
            return
        started, free_before, total = self._started
        self._started = None
        free, _ = torch.cuda.mem_get_info(device)
        self.last = dict(elapsed_seconds=round(time.monotonic() - started, 3),
            device_total_mib=total // 1024**2, device_free_before_mib=free_before // 1024**2,
            device_free_after_mib=free // 1024**2,
            peak_allocated_mib=round(torch.cuda.max_memory_allocated(device) / 1024**2, 1),
            peak_reserved_mib=round(torch.cuda.max_memory_reserved(device) / 1024**2, 1))

    def status(self):
        return dict(consumer=self.consumer, budget_mib=self.budget_mib, reserve_mib=self.reserve_mib,
                    admission_authority="local-worker", allocator_limit="pytorch-only",
                    last_stage=self.last)
