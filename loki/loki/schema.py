"""
Loki System Model — Schema v0.1
Host: a single-box deployment — one 24 GB GPU, a modern multi-core CPU, 96 GB RAM, Linux.

Eleven top-level domains:
  hardware      — static, calibrated once
  tiers         — live state per tier T1–T5 (T6 offline by default)
  workloads     — active / pending / completed rolling window
  schedule      — 24h forward forecast
  quotas        — cloud API budgets and burn rates
  resources     — live VRAM / RAM / CPU
  events        — append-only rolling log (~24h)
  health        — per-component health checks
  operator      — operator preferences and presence state
  memory        — 7-layer memory architecture state (L1–L7)
  decisions     — decision-engine domain (Phase 3.1 seed)

Doctrine: schema fields are what Loki must know to function as a manager.
Adding a field is a deliberate decision. Nothing here is inferred from
cardinal decisions — this layer observes reality regardless of doctrine.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum, IntEnum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ─── Enums ────────────────────────────────────────────────────────────────────

class TierState(str, Enum):
    ACTIVE       = "active"
    SOFT_OFFLOAD = "soft_offload"
    STOPPED      = "stopped"
    FAILED       = "failed"
    STARTING     = "starting"
    STOPPING     = "stopping"
    OFFLINE      = "offline"   # T6 default — not part of current profile

class HealthStatus(str, Enum):
    OK           = "ok"
    DEGRADED     = "degraded"
    UNRESPONSIVE = "unresponsive"
    STOPPED      = "stopped"    # expected stopped (by profile)
    IDLE         = "idle"       # burst-only tier, cleanly offloaded (marker file present)
    ERROR        = "error"
    UNKNOWN      = "unknown"

class OOMRisk(str, Enum):
    LOW      = "low"
    ELEVATED = "elevated"
    IMMINENT = "imminent"

class WorkloadType(str, Enum):
    SCHEDULED   = "scheduled"
    HERMES_CRON = "hermes_cron"
    OPERATOR    = "operator"
    N8N         = "n8n"
    MANUAL      = "manual"

class WorkloadOutcome(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED  = "failed"
    TIMEOUT = "timeout"
    KILLED  = "killed"

class QuotaStatus(str, Enum):
    OK               = "ok"
    APPROACHING_WALL = "approaching_wall"
    WALLED           = "walled"

class OperatorState(str, Enum):
    ACTIVE   = "active"
    IDLE     = "idle"
    SLEEPING = "sleeping"
    UNKNOWN  = "unknown"

class MemoryLayerHealth(str, Enum):
    OK             = "ok"
    DEGRADED       = "degraded"
    UNRESPONSIVE   = "unresponsive"
    NOT_CONFIGURED = "not_configured"   # layer not yet built (e.g. L1 Redis → P1.5-6)
    UNKNOWN        = "unknown"


# ─── Hardware (static) ────────────────────────────────────────────────────────

class GPUHardware(BaseModel):
    model: str                   = "RTX 3090 FE"
    vram_total_mb: int           = 24576
    vram_reserve_driver_mb: int  = 512
    vram_usable_mb: int          = 24064
    arch: str                    = "Ampere SM86"
    cuda_capability: str         = "8.6"
    pcie_gen: int                = 4
    pcie_lanes: int              = 16
    pcie_bandwidth_gbps: float   = 32.0

class CPUHardware(BaseModel):
    model: str          = "Ryzen 9 9900X"
    cores_total: int    = 12
    cores_reserved: int = 2
    cores_available: int = 10

class RAMHardware(BaseModel):
    total_mb: int             = 98304
    ddr_generation: str       = "DDR5"
    speed_mts: int            = 6000
    bandwidth_gbps: float     = 96.0

class StorageHardware(BaseModel):
    nvme_path: str     = "~"
    nvme_total_gb: int = 4096
    models_cache: str  = "~/.cache/huggingface/hub"
    # Models loaded via -hf <org>/<repo>:<quant> shortcut syntax.
    # No ~/models/ migration planned — HF cache is the storage substrate.

class GPUTelemetry(BaseModel):
    """Live GPU readings sampled by the hardware listener (nvidia-smi)."""
    temperature_c: Optional[int]       = None
    fan_percent: Optional[int]         = None
    utilization_percent: Optional[int] = None
    power_watts: Optional[float]       = None
    memory_used_mb: Optional[int]      = None
    thermal_state: str                 = "unknown"  # ok | warn | critical | unknown

class HardwareHealth(BaseModel):
    """Live host hardware telemetry (hardware.py listener). Distinct from the
    static Hardware specs: sampled each poll, where the specs are fixed config.
    String status fields use 'unavailable' when the probe surface is absent
    (no smartctl, no EDAC controller) — never an error."""
    gpu: GPUTelemetry          = Field(default_factory=GPUTelemetry)
    disk_smart: str            = "unknown"   # ok | failing | unavailable | unknown
    disk_detail: Optional[str] = None
    ram_ecc_status: str        = "unknown"   # ok | errors | unavailable | unknown
    ram_ecc_correctable: Optional[int]   = None
    ram_ecc_uncorrectable: Optional[int] = None
    updated_at: Optional[datetime] = None
    notes: List[str]           = Field(default_factory=list)

class Hardware(BaseModel):
    gpu: GPUHardware      = Field(default_factory=GPUHardware)
    cpu: CPUHardware      = Field(default_factory=CPUHardware)
    ram: RAMHardware      = Field(default_factory=RAMHardware)
    storage: StorageHardware = Field(default_factory=StorageHardware)
    health: HardwareHealth = Field(default_factory=HardwareHealth)
    cuda_pinned_version: str = "12.8"
    cuda_pin_packages: int   = 11   # apt-mark hold count; verify quarterly


# ─── Tiers ────────────────────────────────────────────────────────────────────

class TierConfig(BaseModel):
    tier_id: str
    enabled: bool
    model: str
    quant: str
    engine: str            = "llama-server"
    context_size: int      = 0
    expert_offload_pct: int = 0   # % routed experts on CPU (MoE only)
    parallelism_np: int    = 1
    active_lora: Optional[str] = None
    port: int
    cpu_only: bool         = False  # CUDA_VISIBLE_DEVICES= set
    burst_only: bool       = False  # if True, skipped by standard inference-up bringup

class TierRuntime(BaseModel):
    state: TierState              = TierState.STOPPED
    pid: Optional[int]            = None
    uptime_sec: Optional[int]     = None
    # Process-observation fields — owned by process.py (master_summary §12.4).
    rss_mb: int                   = 0
    cpu_pct: float                = 0.0
    restart_count_24h: int        = 0
    last_restart_ts: Optional[datetime] = None
    # Substrate Pressure Cascade self-offload state (§10.3) — set by process.py
    # from the t1_offload_marker. True = running at a reduced -ngl (GPU→CPU/DDR5).
    offloaded: bool               = False
    offload_ngl: Optional[int]    = None
    # In-flight request count for burst tiers, from the llama-server /slots probe
    # (tier_health.py). None = not probed / endpoint unavailable (treated as
    # UNKNOWN — never as idle); 0 = up but idle (safe to evict under §10.3
    # pressure); >0 = actively serving. Only populated for BURST_TIERS.
    active_requests: Optional[int] = None
    last_health_check: Optional[datetime] = None
    health_status: HealthStatus   = HealthStatus.UNKNOWN

class TierResources(BaseModel):
    vram_used_mb: int       = 0
    vram_kv_cache_mb: int   = 0
    ram_resident_mb: int    = 0
    cpu_percent_avg_60s: float = 0.0
    page_cache_mb: int      = 0

class TierPerformance(BaseModel):
    tok_per_sec_recent: Optional[float]   = None
    tok_per_sec_baseline: Optional[float] = None
    prompt_eval_tok_per_sec: Optional[float] = None
    completions_in_window: int = 0
    errors_in_window: int      = 0

class Tier(BaseModel):
    config: TierConfig
    runtime: TierRuntime       = Field(default_factory=TierRuntime)
    resources: TierResources   = Field(default_factory=TierResources)
    performance: TierPerformance = Field(default_factory=TierPerformance)


# ─── Workloads ────────────────────────────────────────────────────────────────

class ActiveWorkload(BaseModel):
    workload_id: str
    type: WorkloadType
    source: str
    started_at: datetime
    expected_completion: Optional[datetime] = None
    progress_pct: Optional[int]   = None
    progress_detail: Optional[str] = None
    tier_dependencies: List[str]  = Field(default_factory=list)
    blocks: List[str]             = Field(default_factory=list)
    blocked_by: List[str]         = Field(default_factory=list)
    priority: str                 = "normal"
    sla_target: Optional[str]     = None

class PendingWorkload(BaseModel):
    workload_id: str
    type: WorkloadType
    scheduled_for: Optional[datetime] = None
    expected_duration_sec: Optional[int] = None
    tier_requirements: List[Dict[str, str]] = Field(default_factory=list)
    priority: str           = "normal"
    sla_target: Optional[str] = None
    conflicts_detected: List[str] = Field(default_factory=list)

class CompletedWorkload(BaseModel):
    workload_id: str
    type: WorkloadType
    started_at: datetime
    completed_at: datetime
    duration_sec: int
    outcome: WorkloadOutcome
    sla_met: Optional[bool]      = None
    output_summary: Optional[str] = None
    anomalies: List[str]         = Field(default_factory=list)
    tier_used: Optional[str]     = None

class Workloads(BaseModel):
    active: List[ActiveWorkload]     = Field(default_factory=list)
    pending: List[PendingWorkload]   = Field(default_factory=list)
    completed: List[CompletedWorkload] = Field(default_factory=list)
    completed_retention_hours: int   = 168   # 7 days


# ─── Schedule ─────────────────────────────────────────────────────────────────

class ScheduledEvent(BaseModel):
    event_id: str
    scheduled_for: datetime
    source: str                  # "cron" | "hermes" | "operator"
    expected_duration_sec: Optional[int] = None
    tier_requirements: List[str] = Field(default_factory=list)
    vram_estimate_mb: int        = 0
    priority: str                = "normal"
    sla_target: Optional[str]    = None
    conflicts: List[Dict[str, Any]] = Field(default_factory=list)

# ─── Cron reconciliation (cron.py, master_summary §12.4) ──────────────────────
# All datetimes are UTC; cron is parsed in system-local tz then converted.

class CronJob(BaseModel):
    name: str                          # target-script basename
    schedule: str                      # cron expression (5 fields or @macro)
    command: str                       # full command, redirect stripped
    log_path: Optional[str]   = None   # derived from the `>>` redirect
    source: str               = "crontab"   # "crontab" | "/etc/cron.d/<file>"
    next_run: Optional[datetime] = None

class MissedRun(BaseModel):
    name: str
    scheduled_for: datetime
    log_path: Optional[str]        = None
    last_log_mtime: Optional[datetime] = None

class ScheduledRun(BaseModel):
    name: str
    next_run: datetime

class Collision(BaseModel):
    job_a: str
    job_b: str
    run_a: datetime
    run_b: datetime
    gap_sec: int


class Schedule(BaseModel):
    forecast_window_hours: int   = 24
    generated_at: datetime       = Field(default_factory=lambda: datetime.now(timezone.utc))
    upcoming: List[ScheduledEvent] = Field(default_factory=list)
    # cron.py (master_summary §12.4)
    cron_entries: List[CronJob]      = Field(default_factory=list)
    missed_runs_24h: List[MissedRun] = Field(default_factory=list)
    upcoming_60min: List[ScheduledRun] = Field(default_factory=list)
    collisions: List[Collision]      = Field(default_factory=list)
    stale_entries: List[str]         = Field(default_factory=list)
    cron_updated_at: Optional[datetime] = None


# ─── Quotas ───────────────────────────────────────────────────────────────────

class CloudQuota(BaseModel):
    name: str
    provider: str
    period: str                          # "weekly" | "monthly"
    period_start: Optional[datetime]     = None
    period_end: Optional[datetime]       = None
    used_pct: Optional[float]            = None   # for Pro subscriptions
    used_usd: Optional[float]            = None   # for API quotas
    budget_usd: Optional[float]          = None
    burn_rate_per_hour: Optional[float]  = None   # pct/hr or usd/hr
    projected_wall_at: Optional[datetime] = None
    status: QuotaStatus                  = QuotaStatus.OK
    threshold_warning_pct: float         = 80.0
    threshold_critical_pct: float        = 95.0
    last_updated: Optional[datetime]     = None
    # Spend/token tracking fields — owned by quota.py (master_summary §12.4).
    tokens_in_today: int                 = 0
    tokens_out_today: int                = 0
    spend_today_usd: float               = 0.0
    last_call_ts: Optional[datetime]     = None
    walls_in_window: int                 = 0   # 429 count; not in spend_logs — see quota.py

class Quotas(BaseModel):
    # Populated by quota_listener. Keys match CloudQuota.name.
    quotas: Dict[str, CloudQuota] = Field(default_factory=dict)


# ─── Resources (live) ─────────────────────────────────────────────────────────

class VRAMByTier(BaseModel):
    t1: int = 0
    t2: int = 0
    t3: int = 0
    t4: int = 0
    t5: int = 0
    t6: int = 0
    driver_display: int = 0
    other: int = 0

class VRAMResources(BaseModel):
    total_mb: int          = 24576
    used_mb: int           = 0
    free_mb: int           = 24576
    used_by_tier: VRAMByTier = Field(default_factory=VRAMByTier)
    oom_risk: OOMRisk      = OOMRisk.LOW
    # Baseline operational target — flag when actual usage exceeds this.
    # 80% target = 19,661 MiB used / 4,915 MiB headroom for workload growth.
    baseline_target_pct: float = 80.0
    updated_at: Optional[datetime] = None

class PageCacheEntry(BaseModel):
    model: str
    cached_mb: int

class RAMResources(BaseModel):
    total_mb: int          = 98304
    used_mb: int           = 0
    free_mb: int           = 98304
    cached_mb: int         = 0
    swap_used_mb: int      = 0
    page_cache_models: List[PageCacheEntry] = Field(default_factory=list)
    updated_at: Optional[datetime] = None

class CPUResources(BaseModel):
    load_avg_1m: float  = 0.0
    load_avg_5m: float  = 0.0
    load_avg_15m: float = 0.0
    updated_at: Optional[datetime] = None

class Resources(BaseModel):
    vram: VRAMResources = Field(default_factory=VRAMResources)
    ram: RAMResources   = Field(default_factory=RAMResources)
    cpu: CPUResources   = Field(default_factory=CPUResources)


# ─── Operator ─────────────────────────────────────────────────────────────────

class OperatorPreferences(BaseModel):
    voice_during_active: bool   = True
    voice_during_idle: bool     = False
    voice_during_sleeping: bool = False
    overnight_window_start: str = "23:00"
    overnight_window_end: str   = "07:00"

class Operator(BaseModel):
    state: OperatorState          = OperatorState.UNKNOWN
    state_confidence: float       = 0.0
    last_input_detected: Optional[datetime] = None
    active_session_id: Optional[str] = None
    preferences: OperatorPreferences = Field(default_factory=OperatorPreferences)
    updated_at: Optional[datetime] = None


# ─── Events ───────────────────────────────────────────────────────────────────

class Event(BaseModel):
    event_id: str
    timestamp: datetime          = Field(default_factory=lambda: datetime.now(timezone.utc))
    type: str                    # e.g. "tier_state_change", "oom_risk_elevated"
    severity: str                = "info"   # "info" | "warning" | "critical"
    tier: Optional[str]          = None
    workload_id: Optional[str]   = None
    detail: Optional[str]        = None
    data: Dict[str, Any]         = Field(default_factory=dict)

class Events(BaseModel):
    retention_hours: int   = 24
    log: List[Event]       = Field(default_factory=list)


# ─── Decisions (engine.py + authority.py, master_summary §12.6 / §9.5) ────────
# The decision engine's read-only projection onto the system model. The engine
# is a pure CONSUMER of StateStore snapshots; the only domain it writes is this
# one (pending asks + a read-only ledger projection for loki-q). The durable
# N=12 trust counters live in authority.json (NOT state.json — §0.1 rule 5:
# state.json is non-doctrine, pruned/rehydrated on cold-start). ActionRecord is
# the ledger row shape; it is mirrored here purely so the CLI can render it.

class ActionTier(IntEnum):
    TIER_1 = 1   # autonomous-immediate (silent)
    TIER_2 = 2   # autonomous-with-log
    TIER_3 = 3   # surface-and-ask

class ActionLifecycleState(str, Enum):
    COLD_START = "cold_start"
    ELIGIBLE   = "eligible"     # hit N=12; promotion ask pending operator approval
    PROMOTED   = "promoted"
    DEMOTED    = "demoted"

class ProposedAction(BaseModel):
    action_id: str                       # behavior id, e.g. "auto_restart_cpu_dataplane_tier"
    trigger: str                         # "process.py:tier_crashed:t5"
    params: Dict[str, Any] = Field(default_factory=dict)   # {"tier": "t5"}
    dedup_key: str                       # stable per incident; cooldown key
    rationale: str
    proposed_at: datetime
    # Proposal provenance. "rule" = a deterministic rule (the trust ladder's
    # earned autonomy applies). Anything else (e.g. "supervisor") is a non-rule
    # proposer: the gate floors it to a BLOCKING Tier-3 ask and never lets it
    # touch the N=12 trust counters, so an LLM proposer can never inherit the
    # autonomy a rule earned. (§9.5 — the supervisor is a proposal source, never
    # an authority.)
    origin: str = "rule"

class ActionRecord(BaseModel):           # ledger row (canonical store = authority.json)
    action_id: str
    description: str = ""
    current_tier: ActionTier = ActionTier.TIER_3
    target_tier: ActionTier  = ActionTier.TIER_2     # promotion cap (seed = TIER_2)
    clean_run_count: int = 0             # consecutive clean runs at current tier
    total_runs: int = 0
    last_fired: Optional[datetime] = None
    last_outcome: Optional[str] = None   # "ok" | "failed" | "regretted"
    state: ActionLifecycleState = ActionLifecycleState.COLD_START
    demotion_reason: Optional[str] = None

class PendingAsk(BaseModel):
    action_id: str
    params: Dict[str, Any] = Field(default_factory=dict)
    rationale: str
    proposed_at: datetime
    tier: ActionTier = ActionTier.TIER_3
    kind: str = "run"                    # "run" = per-run approval | "promotion" = N=12 ladder
    blocking: bool = True                # non-blocking = timer + default-proceed (§9.5.1; live 2026-06-16)
    expires_at: Optional[datetime] = None   # non-blocking deadline; gate default-proceeds at timeout
    origin: str = "rule"                 # carries ProposedAction.origin so the engine/gate keep
                                         # non-rule asks blocking + out of the trust ladder

class Decisions(BaseModel):
    pending_asks: List[PendingAsk] = Field(default_factory=list)
    ledger: List[ActionRecord]     = Field(default_factory=list)   # read-only projection
    last_tick: Optional[datetime]  = None


# ─── Health ───────────────────────────────────────────────────────────────────

class ComponentHealth(BaseModel):
    name: str
    status: HealthStatus           = HealthStatus.UNKNOWN
    last_check: Optional[datetime] = None
    last_seen_healthy: Optional[datetime] = None
    response_ms: Optional[int]     = None
    detail: Optional[str]          = None
    port: Optional[int]            = None

class Health(BaseModel):
    components: List[ComponentHealth] = Field(default_factory=list)
    last_full_sweep: Optional[datetime] = None


# ─── Memory layers (memory.py, MEMORY_ARCHITECTURE §10.2) ─────────────────────
# The 7-layer monarch memory architecture Loki observes as Arbiter. memory.py
# actively probes the layers it owns (L3 pgvector SQL, L4 Hermes HTTP + state.db
# mtime, L6 vault git) and mirrors the rest from existing signals (L2/L5/L7 from
# health components; L1 is a not_configured placeholder until P1.5-6). Per-layer
# health/activity/anomaly signals and cadences are defined in §10.1.

class MemoryLayer(BaseModel):
    layer: str                              # "L1".."L7"
    name: str                               # "Redis", "pgvector", "Hermes", …
    role: str                               # "Truth" | "Index" | "Memory"
    mode: str                               # "probe" | "state" | "placeholder"
    health: MemoryLayerHealth = MemoryLayerHealth.UNKNOWN
    health_signal: Optional[str]   = None   # what the probe checked / its result
    activity_signal: Optional[str] = None   # e.g. "85 chunks", "state.db 21h ago"
    anomaly: Optional[str]         = None   # set when an anomaly is detected
    source_component: Optional[str] = None  # health-component name for mode=state
    last_check: Optional[datetime] = None
    last_seen_healthy: Optional[datetime] = None
    response_ms: Optional[int]     = None


def _default_memory_layers() -> Dict[str, "MemoryLayer"]:
    """Cold-start the 7 layer slots from MONARCH_MEMORY_LAYERS. Also fires when
    load_from_disk() reads a state.json predating the memory domain."""
    return {
        m["layer"]: MemoryLayer(
            layer=m["layer"], name=m["name"], role=m["role"], mode=m["mode"],
            source_component=m.get("component"),
            health=(MemoryLayerHealth.NOT_CONFIGURED if m["mode"] == "placeholder"
                    else MemoryLayerHealth.UNKNOWN),
        )
        for m in MONARCH_MEMORY_LAYERS
    }


class MemoryLayers(BaseModel):
    layers: Dict[str, MemoryLayer]   = Field(default_factory=_default_memory_layers)
    skill_drafts_total: int          = 0
    skill_drafts_stale: List[str]    = Field(default_factory=list)
    # Curated-tier GC proposals (MEMORY_ARCHITECTURE §8.8 janitor). Same
    # disk-backed, operator-gated draft-state pattern as skill_drafts.
    gc_proposals_total: int          = 0
    gc_proposals_stale: List[str]    = Field(default_factory=list)
    last_sweep: Optional[datetime]   = None


# ─── Top-level SystemModel ────────────────────────────────────────────────────

class SystemModel(BaseModel):
    """
    The canonical in-memory model of monarch's state.
    Written to ~/.local/state/loki/state.json every 10s by the daemon.
    Read by loki-q CLI and (eventually) the Loki decision engine.
    """
    # Label field only — read by humans and logs, never acted on by migration
    # logic. Cold-cycle discipline is the migration strategy for this stack. (D4)
    schema_version: str     = "0.1.0"
    hardware: Hardware      = Field(default_factory=Hardware)
    tiers: Dict[str, Tier]  = Field(default_factory=dict)
    workloads: Workloads    = Field(default_factory=Workloads)
    schedule: Schedule      = Field(default_factory=Schedule)
    quotas: Quotas          = Field(default_factory=Quotas)
    resources: Resources    = Field(default_factory=Resources)
    operator: Operator      = Field(default_factory=Operator)
    events: Events          = Field(default_factory=Events)
    health: Health          = Field(default_factory=Health)
    memory: MemoryLayers    = Field(default_factory=MemoryLayers)
    decisions: Decisions    = Field(default_factory=Decisions)
    last_updated: datetime  = Field(default_factory=lambda: datetime.now(timezone.utc))
    daemon_pid: Optional[int] = None


# ─── Monarch v18 baseline tier configuration ──────────────────────────────────
# Hardcoded from confirmed inference-up script (May 2026).
# Update these if inference-up changes.

MONARCH_TIERS: Dict[str, TierConfig] = {
    "t1": TierConfig(
        tier_id="t1", enabled=True,
        model="Qwen3.6-27B", quant="UD-Q4_K_XL",
        context_size=24576, parallelism_np=1, port=8080,
    ),
    "t2": TierConfig(
        tier_id="t2", enabled=True,
        model="Qwen3.6-27B", quant="UD-Q4_K_XL",
        context_size=16384, parallelism_np=1, port=8083,
        burst_only=True,
    ),
    "t3": TierConfig(
        tier_id="t3", enabled=True,
        model="Qwen3.6-27B", quant="UD-Q4_K_XL",
        context_size=8192, parallelism_np=1, port=8084, cpu_only=True,
    ),
    "t4": TierConfig(
        tier_id="t4", enabled=True,
        model="Phi-4-mini", quant="Q4_K_M",
        context_size=16384, parallelism_np=4, port=8002, cpu_only=True,
        # 2026-06-16: CPU-resident (validation gate is the only consumer; grader
        # calls are short/async). Frees ~4.2 GB VRAM for T1/T2/T6. See §5.4.
    ),
    "t5": TierConfig(
        tier_id="t5", enabled=True,
        model="Qwen3-1.7B", quant="Q5_K_M",
        context_size=8192, parallelism_np=1, port=8085, cpu_only=True,
    ),
    "t6": TierConfig(
        tier_id="t6", enabled=False,  # offline by default
        model="Qwen3.6-35B-A3B", quant="UD-Q4_K_XL",
        context_size=65536, parallelism_np=1, port=8086,
        expert_offload_pct=35,  # n_cpu_moe=14 measured operating point (E3 2026-05-30)
    ),
}

# Restartable zero-VRAM CPU dataplane tiers, DERIVED from MONARCH_TIERS so the
# crash-detection rule (rules.py) and the restart action (restart_dataplane_tier.py)
# stay in lockstep with tier config — no hand-maintained {"t3","t5"} literals to
# drift if a tier's cpu_only/enabled flags change. Evaluates to ("t3", "t4", "t5") today.
CPU_DATAPLANE_TIERS: tuple[str, ...] = tuple(
    tid for tid, cfg in MONARCH_TIERS.items() if cfg.cpu_only and cfg.enabled
)

# Evictable burst tiers, DERIVED from MONARCH_TIERS (burst_only & enabled) so the
# §10.3 cascade eviction rule (rules.py) and action (evict_burst.py) stay in
# lockstep with tier config — no hand-maintained literals. Evaluates to ("t2",)
# today; T6 joins automatically once it flips enabled=True (it is burst-only by
# role but ships offline by default, §5.6).
BURST_TIERS: tuple[str, ...] = tuple(
    tid for tid, cfg in MONARCH_TIERS.items() if cfg.burst_only and cfg.enabled
)

# Flapping guard: >= this many restarts in 24h means a tier is restart-looping;
# don't auto-bounce it — surface to the operator instead. Single source shared by
# process.py (emits the warning), rules.py (suppresses the proposal), and
# authority.py (forces Tier 3 on a flapping tier).
FLAP_THRESHOLD_24H = 3

# ─── D4 role → model mapping (P2-2 role-key indirection, 2026-06-10) ──────────
# Quota rows, cascade doctrine (§9.4/§9.5.4), and quota.py's spend-log
# attribution key on ROLE, not on provider model-name strings. Born from
# NEW-v20-1: the deepseek_v3 → deepseek_v4_flash rename orphaned a state.json
# quota key; with roles, a model rename touches exactly this table (plus the
# model defs in ~/litellm/config.yaml) and state.json transitions automatically
# via StateStore.load_from_disk() prune/hydrate — renamed/rekeyed rows re-enter
# promotion counting at N=0 per strict cold-start.
#
# Spec fields:
#   provider        — billing/provider label carried into CloudQuota.provider.
#   model           — canonical model string for the role (doctrine display).
#   period          — quota period for the row ("weekly" | "monthly").
#   budget_usd      — prepaid budget; None = untracked/subscription/vestigial.
#   api_metered     — True: spend tracked in USD (used_usd starts 0.0);
#                     False: subscription tracked by used_pct (used_usd None).
#   litellm_models  — every spend_logs.model string LiteLLM may write for this
#                     role (provider-prefixed variants included). Empty tuple =
#                     role never traverses LiteLLM (Pro subscriptions, local T6).
#   quota_row       — False: cascade-reference-only role, no CloudQuota row
#                     (local inference is $0 — nothing to meter).
ROLE_MODELS: Dict[str, Dict[str, Any]] = {
    # Workflow-tier-zero — operator-driven Claude Pro subscriptions (×3 per
    # operator.md, G-2 2026-06-10). OUTSIDE the Quota Cascade: rows are
    # wall/usage telemetry for Pro-rotation discipline, never routing inputs.
    "pro_1": {"provider": "anthropic", "model": "claude-pro", "period": "weekly",
              "budget_usd": None, "api_metered": False, "litellm_models": ()},
    "pro_2": {"provider": "anthropic", "model": "claude-pro", "period": "weekly",
              "budget_usd": None, "api_metered": False, "litellm_models": ()},
    "pro_3": {"provider": "anthropic", "model": "claude-pro", "period": "weekly",
              "budget_usd": None, "api_metered": False, "litellm_models": ()},
    # Peer rotation (D4) — active workhorse pair, fullest-peer rule (§9.5.4).
    "peer_a": {"provider": "deepseek", "model": "deepseek-v4-flash",
               "period": "monthly", "budget_usd": 20.0, "api_metered": True,
               "litellm_models": ("deepseek-v4-flash", "deepseek/deepseek-v4-flash")},
    "peer_b": {"provider": "moonshot", "model": "kimi-k2.6",
               "period": "monthly", "budget_usd": 10.0, "api_metered": True,
               # Provider-side id is kimi-k2.6 (dot) — the k2-6 variants cover
               # historical spend rows written before the 2026-06-10 id fix.
               "litellm_models": ("kimi-k2.6", "moonshot/kimi-k2.6",
                                  "kimi-k2-6", "moonshot/kimi-k2-6")},
    # Emergency rung — STRUCK from D4 2026-06-09 (no ANTHROPIC_API_KEY on disk);
    # vestigial forward-compat row (was anthropic_api_direct, NEW-v20-7). If
    # re-provisioned, wiring pins claude-opus-4-8 (ZDR) per P1-1 — never an
    # alias that could float to Fable.
    "frontier_direct": {"provider": "anthropic", "model": "claude-opus-4-8",
                        "period": "monthly", "budget_usd": None,
                        "api_metered": True, "litellm_models": ()},
    # Reserve coder — T6 local (D1/D5 §11.5). Cascade-reference role only:
    # local inference is $0, no quota row to meter.
    "coder_local": {"provider": "local", "model": "qwen-coder-deep",
                    "period": "monthly", "budget_usd": None,
                    "api_metered": False, "litellm_models": (), "quota_row": False},
}

# Roles that materialize as CloudQuota rows in state.json (single source for
# state.py's canonical key set — keep no hand-maintained copy anywhere else).
QUOTA_ROLE_KEYS: frozenset[str] = frozenset(
    role for role, spec in ROLE_MODELS.items() if spec.get("quota_row", True)
)

MONARCH_HEALTH_COMPONENTS = [
    {"name": "llama-server-t1",    "port": 8080},
    {"name": "llama-server-t2",    "port": 8083},
    {"name": "llama-server-t3",    "port": 8084},
    {"name": "llama-server-t4",    "port": 8002},
    {"name": "llama-server-t5",    "port": 8085},
    {"name": "litellm",            "port": 4000},
    {"name": "validation-gate",    "port": 4100},
    {"name": "lora-dispatcher",    "port": 4200},
    {"name": "n8n",                "port": 5678},
    {"name": "postgres",           "port": 5432},
    {"name": "monarch-postgres",   "port": 5433},
    {"name": "embed-nomic",        "port": 8087},
    {"name": "codebase-memory",    "port": None},   # stdio MCP; CLI-probed
    {"name": "hermes",             "port": 8642},   # /v1/models, bearer auth
    {"name": "rerank-bge",         "port": 8088},   # llama-server reranker (/health), L7 EverCore rerank
    {"name": "evercore",           "port": 1995},   # L7 EverMemOS; composite probe (ES/Milvus/Mongo/Redis:6380/API:1995)
    {"name": "l1-redis",           "port": 6379},   # L1 hot operational truth (P1.5-6); container l1-redis, TCP probe
]

# ─── Memory architecture layers (MEMORY_ARCHITECTURE §10) ─────────────────────
# Source-of-truth for the memory domain memory.py observes. mode:
#   probe       — memory.py actively probes; it owns the signal (§10.2)
#   state       — mirrored from an existing health component; no re-probe
#                 (same non-duplication discipline as tier_health ↔ process)
#   placeholder — not yet built; initializes not_configured (none since P1.5-6)
# Boundaries locked 2026-05-29: active probes are {L3, L4, L6}.
MONARCH_MEMORY_LAYERS = [
    {"layer": "L1", "name": "Redis",           "role": "Truth",  "mode": "state", "component": "l1-redis"},
    {"layer": "L2", "name": "Postgres",        "role": "Truth",  "mode": "state", "component": "postgres"},
    {"layer": "L3", "name": "pgvector",        "role": "Index",  "mode": "probe"},
    {"layer": "L4", "name": "Hermes",          "role": "Memory", "mode": "probe"},
    {"layer": "L5", "name": "Codebase-Memory", "role": "Index",  "mode": "state", "component": "codebase-memory"},
    {"layer": "L6", "name": "Obsidian vault",  "role": "Truth",  "mode": "probe"},
    {"layer": "L7", "name": "EverCore",        "role": "Memory", "mode": "state", "component": "evercore"},
]

# Port → tier_id mapping (used by VRAM listener to attribute GPU memory).
# DERIVED from MONARCH_TIERS — same lockstep rationale as CPU_DATAPLANE_TIERS:
# a tier port change in one place must not leave a stale hand-maintained copy.
PORT_TO_TIER: Dict[int, str] = {cfg.port: tid for tid, cfg in MONARCH_TIERS.items()}

# Documented VRAM baselines (MiB) from inference-up measured values
VRAM_BASELINE: Dict[str, int] = {
    "t1": 11500,
    "t2": 5500,
    "t3": 500,
    "t4": 0,      # 2026-06-16: CPU-resident (CUDA_VISIBLE_DEVICES=, -ngl 0); see §5.4
    "t5": 0,
    "t6": 0,   # offline
    "driver_display": 512,
}
