"""MITRE ATT&CK technique catalog — minimal subset relevant to Overwatch alerts."""

ATTACK_TECHNIQUES = {
    "T1059":     ("Command and Scripting Interpreter", "Adversaries abuse command interpreters to execute commands or scripts."),
    "T1059.001": ("PowerShell",                       "Execution of arbitrary commands through PowerShell."),
    "T1059.003": ("Windows Command Shell",            "Execution through cmd.exe."),
    "T1059.005": ("Visual Basic",                     "Execution of VBScript through wscript or cscript."),
    "T1059.007": ("JavaScript",                       "Execution of JScript / JS through wscript or mshta."),
    "T1027":     ("Obfuscated Files or Information",  "Encoded or obfuscated commands and files."),
    "T1140":     ("Deobfuscate/Decode Files",         "Decoding base64, hex, or compressed payloads."),
    "T1564":     ("Hide Artifacts",                   "Hidden windows, registry, or files used to mask activity."),
    "T1218":     ("System Binary Proxy Execution",    "Using signed Microsoft binaries (LOLBins) to execute payloads."),
    "T1218.005": ("Mshta",                            "Execution via mshta.exe."),
    "T1218.011": ("Rundll32",                         "Execution via rundll32.exe."),
    "T1218.010": ("Regsvr32",                         "Execution via regsvr32.exe."),
    "T1078":     ("Valid Accounts",                   "Use of valid credentials for access."),
    "T1021.001": ("Remote Desktop Protocol",          "Lateral movement or access via RDP."),
    "T1133":     ("External Remote Services",         "Use of remote services from the internet."),
    "T1219":     ("Remote Access Software",           "TeamViewer, AnyDesk, VNC and similar tools."),
    "T1136":     ("Create Account",                   "Adversaries create local or domain accounts."),
    "T1087":     ("Account Discovery",                "whoami, net user, AD discovery commands."),
    "T1083":     ("File and Directory Discovery",     "Enumerating files and directories."),
    "T1018":     ("Remote System Discovery",          "Discovering hosts on the network."),
    "T1057":     ("Process Discovery",                "Enumerating running processes."),
    "T1490":     ("Inhibit System Recovery",          "Deleting shadow copies, disabling recovery."),
    "T1485":     ("Data Destruction",                 "Destruction or deletion of data."),
    "T1486":     ("Data Encrypted for Impact",        "Ransomware-style encryption."),
    "T1547.001": ("Registry Run Keys / Startup Folder", "Persistence via Run keys or Startup folder."),
    "T1053.005": ("Scheduled Task",                   "Persistence via scheduled tasks."),
    "T1543.003": ("Windows Service",                  "Persistence via service creation."),
    "T1091":     ("Replication Through Removable Media", "Malware spreading via USB drives."),
    "T1567.002": ("Exfiltration to Cloud Storage",    "Exfil via cloud storage providers."),
    "T1071.001": ("Web Protocols",                    "C2 traffic over HTTP/HTTPS."),
    "T1110":     ("Brute Force",                      "Password guessing against accounts."),
    "T1110.003": ("Password Spraying",                "Brute force against many accounts."),
    "T1112":     ("Modify Registry",                  "Persistence or evasion via registry edits."),
}


def technique_name(tid: str) -> str:
    return ATTACK_TECHNIQUES.get(tid, (tid, ""))[0]


def technique_url(tid: str) -> str:
    base = tid.split(".")[0]
    sub = tid.split(".")[1] if "." in tid else None
    if sub:
        return f"https://attack.mitre.org/techniques/{base}/{sub}/"
    return f"https://attack.mitre.org/techniques/{base}/"
