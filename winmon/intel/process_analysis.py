"""Process analysis primitives: parent chain, command-line scoring, signing, path heuristics."""

import logging
import re
from typing import Optional

log = logging.getLogger("winmon.intel.process")

# ---- command-line rules ---------------------------------------------------
# Each rule: (regex, score weight, MITRE techniques, friendly reason).
# Higher score = more suspicious. Multiple rules can match — scores combine
# (capped at 100) and tags accumulate.
CMDLINE_RULES = [
    (r"(?:^|\s)-enc(?:odedcommand)?\s",       45, ["T1027", "T1059.001"], "encoded PowerShell payload"),
    (r"(?:^|\s)-e\s+[A-Za-z0-9+/=]{20,}",     45, ["T1027", "T1059.001"], "encoded PowerShell payload"),
    (r"-executionpolicy\s+bypass",            20, ["T1059.001"],          "execution policy bypass"),
    (r"-windowstyle\s+hidden",                25, ["T1564"],              "hidden window"),
    (r"-noni|--?noninteractive",              10, ["T1059.001"],          "non-interactive flag"),
    (r"-noprofile|-nop\b",                    10, ["T1059.001"],          "no profile flag"),
    (r"DownloadString|DownloadFile",          40, ["T1059.001", "T1071.001"], "remote download in script"),
    (r"Invoke-WebRequest|wget |curl ",        25, ["T1071.001"],          "web request from shell"),
    (r"\bIEX\b|Invoke-Expression",            40, ["T1059.001"],          "dynamic code execution"),
    (r"FromBase64String|::Convert\]?::From",  35, ["T1140"],              "base64 decode"),
    (r"net\s+user\s+\S+\s+\S+\s+/add",        55, ["T1136"],              "local user creation"),
    (r"net\s+localgroup\s+administrators",    50, ["T1078"],              "admin group manipulation"),
    (r"whoami\s+/(?:all|groups|priv)",        25, ["T1087"],              "user enumeration"),
    (r"nltest\s+/dclist",                     30, ["T1018"],              "domain controller discovery"),
    (r"net\s+view\b",                         15, ["T1018"],              "network discovery"),
    (r"tasklist\s+/svc",                      15, ["T1057"],              "service enumeration"),
    (r"vssadmin\s+delete\s+shadows",          70, ["T1490"],              "shadow copy deletion"),
    (r"wbadmin\s+delete\s+catalog",           65, ["T1490"],              "backup catalog deletion"),
    (r"bcdedit\s+.*recoveryenabled\s+no",     60, ["T1490"],              "recovery disabled"),
    (r"reg\s+add\s+.*\\Run\\?",               40, ["T1547.001"],          "registry Run key write"),
    (r"schtasks\s+/create",                   35, ["T1053.005"],          "scheduled task creation"),
    (r"sc\s+create\s+",                       40, ["T1543.003"],          "service creation"),
    (r"certutil\s+.*-(?:decode|urlcache)",    50, ["T1140", "T1218"],     "certutil abuse"),
    (r"regsvr32\s+/s\s+/u\s+/i:http",         60, ["T1218.010"],          "regsvr32 squiblydoo"),
    (r"rundll32\s+\S+,\S+",                   25, ["T1218.011"],          "rundll32 with export"),
    (r"mshta\s+(?:vbscript:|javascript:)",    55, ["T1218.005"],          "mshta protocol abuse"),
]

# Compile once
_COMPILED_RULES = [(re.compile(r, re.IGNORECASE), w, t, m) for r, w, t, m in CMDLINE_RULES]

# Watchlisted LOLBins — running these alone is mildly suspicious
LOLBIN_PROCESSES = {
    "powershell.exe": (["T1059.001"], "PowerShell"),
    "pwsh.exe":       (["T1059.001"], "PowerShell"),
    "cmd.exe":        (["T1059.003"], "Command Shell"),
    "wscript.exe":    (["T1059.005"], "Windows Script Host"),
    "cscript.exe":    (["T1059.005"], "Windows Script Host"),
    "mshta.exe":      (["T1218.005"], "Mshta"),
    "rundll32.exe":   (["T1218.011"], "Rundll32"),
    "regsvr32.exe":   (["T1218.010"], "Regsvr32"),
    "certutil.exe":   (["T1140"],     "Certutil"),
    "bitsadmin.exe":  (["T1197"],     "BITS"),
    "msiexec.exe":    (["T1218"],     "MSI Exec"),
}

# Path risk weights — running a binary from these locations is unusual.
_PATH_RISK = [
    (r"\\appdata\\local\\temp\\",      30),
    (r"\\windows\\temp\\",             30),
    (r"\\users\\public\\",             25),
    (r"\\downloads\\",                 20),
    (r"\\appdata\\roaming\\",          15),
    (r"\\programdata\\",               10),
    (r"\\users\\[^\\]+\\desktop\\",    15),
]
_PATH_RISK_COMPILED = [(re.compile(p, re.IGNORECASE), w) for p, w in _PATH_RISK]


# ---- parent process resolution -------------------------------------------

def get_parent_chain(pid: int, max_depth: int = 5) -> list[str]:
    """Walk the parent process chain, returning names ordered immediate → root."""
    chain: list[str] = []
    try:
        import psutil
        try:
            proc = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return chain
        for _ in range(max_depth):
            try:
                parent = proc.parent()
                if parent is None:
                    break
                chain.append(parent.name() or "?")
                proc = parent
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break
    except ImportError:
        pass
    return chain


# ---- signing classifier (path-based heuristic) ---------------------------

def classify_signing(exe_path: Optional[str]) -> str:
    """Lightweight signing classifier based on install location.

    Returns: 'signed_ms' | 'signed_3p' | 'unsigned_or_unknown' | 'unknown'.

    True Authenticode verification is more correct but requires per-event
    PowerShell or WinTrust calls — too slow at process-creation rate. This
    heuristic catches >90% of cases (MS code in Windows\\, 3rd party in
    Program Files\\, malware drops to %TEMP% / %APPDATA% / Public).
    """
    if not exe_path:
        return "unknown"
    p = exe_path.lower().replace("/", "\\")
    if p.startswith("c:\\windows\\"):
        return "signed_ms"
    if p.startswith("c:\\program files\\") or p.startswith("c:\\program files (x86)\\"):
        return "signed_3p"
    if not p.startswith("c:\\"):
        return "unknown"
    return "unsigned_or_unknown"


# ---- path risk scoring ---------------------------------------------------

def score_path(exe_path: Optional[str]) -> tuple[int, list[str]]:
    """Returns (score 0-100, reasons)."""
    if not exe_path:
        return 0, []
    score = 0
    reasons = []
    for pat, weight in _PATH_RISK_COMPILED:
        if pat.search(exe_path):
            score += weight
            reasons.append(f"path under {pat.pattern.strip(chr(92))}")
    return min(score, 100), reasons


# ---- command-line scoring ------------------------------------------------

def score_command_line(cmd: Optional[str]) -> dict:
    """Returns {'score': 0-100, 'tags': [...], 'reasons': [...], 'top_reason': str}."""
    if not cmd:
        return {"score": 0, "tags": [], "reasons": [], "top_reason": ""}

    total = 0
    tags = set()
    reasons = []
    top = ("", 0)

    for pat, weight, mitre, reason in _COMPILED_RULES:
        if pat.search(cmd):
            total += weight
            tags.update(mitre)
            reasons.append(reason)
            if weight > top[1]:
                top = (reason, weight)

    return {
        "score": min(total, 100),
        "tags": sorted(tags),
        "reasons": reasons,
        "top_reason": top[0],
    }


# ---- top-level convenience -----------------------------------------------

def analyse_process(*, name: str, exe: Optional[str], cmd: Optional[str],
                    pid: int, parent_pid: Optional[int] = None,
                    owner: Optional[str] = None) -> dict:
    """Single entry point used by the process monitor.

    Returns a dict with:
        confidence:     0-100 combined risk
        severity:       'info' | 'warning' | 'critical'
        attack_tags:    [MITRE technique IDs]
        parent_tree:    [parent process names from immediate → root]
        signature:      signing classification
        reasons:        list of human-readable reasons
        dedup_key:      stable string for deduplication
    """
    name_l = (name or "").lower()
    parent_tree = get_parent_chain(pid) if pid else []
    cmd_analysis = score_command_line(cmd)
    path_score, path_reasons = score_path(exe)
    signing = classify_signing(exe)

    tags = set(cmd_analysis["tags"])
    if name_l in LOLBIN_PROCESSES:
        lolbin_tags, _ = LOLBIN_PROCESSES[name_l]
        tags.update(lolbin_tags)

    # Combined confidence: cmd + path. LOLBin name adds a small floor.
    confidence = min(cmd_analysis["score"] + path_score, 100)
    if name_l in LOLBIN_PROCESSES and confidence < 15:
        confidence = 15

    # Signing adjustments
    if signing == "signed_ms" and not cmd_analysis["tags"]:
        confidence = max(confidence - 10, 0)  # benign MS binaries get demoted
    elif signing == "unsigned_or_unknown" and confidence > 0:
        confidence = min(confidence + 10, 100)

    # Severity bucketing
    if confidence >= 70:
        severity = "critical"
    elif confidence >= 30:
        severity = "warning"
    else:
        severity = "info"

    reasons = cmd_analysis["reasons"] + path_reasons
    if signing == "unsigned_or_unknown" and confidence >= 20:
        reasons.append("unsigned binary outside standard locations")

    dedup_key = f"process:{name_l}:{cmd_analysis['top_reason'] or 'plain'}"

    return {
        "confidence": confidence,
        "severity": severity,
        "attack_tags": sorted(tags),
        "parent_tree": parent_tree,
        "signature": signing,
        "reasons": reasons,
        "top_reason": cmd_analysis["top_reason"],
        "dedup_key": dedup_key,
    }
