#!/usr/bin/env python3
"""Patches the llamastack Deployment and run-config ConfigMap to use TrustyAI fms safety provider.

Usage: NAMESPACE=<ns> python3 scripts/patch-llamastack-trustyai.py
"""
import json
import os
import subprocess
import sys
import yaml

NAMESPACE = os.environ["NAMESPACE"]

PROVIDER_YAML = (
    "adapter_type: trustyai_fms\n"
    "pip_packages:\n  - llama_stack_provider_trustyai_fms\n"
    "module: llama_stack_provider_trustyai_fms\n"
    "config_class: llama_stack_provider_trustyai_fms.config.FMSSafetyProviderConfig\n"
    "api_dependencies: []\n"
    "optional_api_dependencies: []\n"
)

# Python one-liner run inside the postStart hook; uses single-quotes only so it
# embeds cleanly inside a double-quoted shell -c argument.
REGISTER_SCRIPT = (
    "import urllib.request, json\n"
    "data = json.dumps({"
    "'shield_id': 'granite-guardian', "
    "'provider_shield_id': 'granite-guardian', "
    "'provider_id': 'trustyai_fms', "
    "'params': {'type': 'chat', 'confidence_threshold': 0.5, 'message_types': ['user'], 'verify_ssl': False, 'detectors': {'granite-guardian': {'detector_params': {'risk_name': 'jailbreak'}}}}"
    "}).encode()\n"
    "req = urllib.request.Request('http://localhost:8321/v1/shields', data=data, "
    "headers={'Content-Type': 'application/json'})\n"
    "print(urllib.request.urlopen(req).read().decode())"
)


def oc(*args, stdin=None):
    try:
        r = subprocess.run(["oc"] + list(args), input=stdin, capture_output=True, check=True)
        return r.stdout
    except subprocess.CalledProcessError as e:
        print(f"ERROR: oc {' '.join(args)} failed", file=sys.stderr)
        print(e.stderr.decode(), file=sys.stderr)
        raise


def get_json(resource):
    return json.loads(oc("get", resource, "-n", NAMESPACE, "-o", "json"))


def apply_json(obj):
    oc("apply", "-n", NAMESPACE, "-f", "-", stdin=json.dumps(obj).encode())


# --- 1. Patch run-config ConfigMap ---
print("  Patching run-config ConfigMap...")
cm = get_json("configmap/run-config")
cfg = yaml.safe_load(cm["data"]["config.yaml"])
cfg["external_providers_dir"] = "/mnt/providers.d"
internal_url = f"https://granite-guardrails-orchestrator-service.{NAMESPACE}.svc.cluster.local:8032"
cfg["providers"]["safety"] = [
    {
        "provider_id": "trustyai_fms",
        "provider_type": "remote::trustyai_fms",
        "config": {
            "orchestrator_url": internal_url,
            "verify_ssl": False,
            "shields": {
                "granite-guardian": {
                    "type": "chat",
                    "confidence_threshold": 0.5,
                    "message_types": ["user"],
                    "detectors": {
                        "granite-guardian": {
                            "detector_params": {"risk_name": "jailbreak"},
                        }
                    },
                }
            },
        },
    }
]
cm["data"]["config.yaml"] = yaml.dump(cfg, default_flow_style=False)
apply_json(cm)
print("  run-config updated.")

# --- 2. Patch llamastack Deployment ---
print("  Patching llamastack Deployment...")
deploy = get_json("deployment/llamastack")
spec = deploy["spec"]["template"]["spec"]

# Use the same image as the main container so pip is available
main_image = next(c["image"] for c in spec["containers"] if c["name"] == "llama-stack")

# Init container: install pip package + write provider definition file.
# repr(PROVIDER_YAML) produces a Python string literal (e.g. 'pip_packages:\n...')
# that Python will interpret correctly when passed to -c.
init_cmd = (
    "pip install llama_stack_provider_trustyai_fms "
    "--target=/mnt/extra-packages --quiet --no-cache-dir && "
    "mkdir -p /mnt/providers.d/remote/safety && "
    f"python3 -c \"open('/mnt/providers.d/remote/safety/trustyai_fms.yaml', 'w')"
    f".write({repr(PROVIDER_YAML)})\""
)

# postStart hook: retry loop gives LlamaStack time to come up before registering.
# Always exits 0 (via trailing `true`) so a slow start doesn't kill the container.
post_start_cmd = (
    "i=0; while [ $i -lt 60 ]; do i=$((i+1)); sleep 5; "
    f'python3 -c "{REGISTER_SCRIPT}" && '
    "echo 'granite-guardian shield registered' && break; done; true"
)

# Volumes: add emptyDirs, replacing any previous version
vols = [v for v in spec.get("volumes", []) if v["name"] not in ("extra-packages", "providers-dir")]
vols += [
    {"name": "extra-packages", "emptyDir": {}},
    {"name": "providers-dir", "emptyDir": {}},
]
spec["volumes"] = vols

# Init containers: add installer, replacing any previous version
inits = [ic for ic in spec.get("initContainers", []) if ic["name"] != "install-trustyai-fms"]
inits.append(
    {
        "name": "install-trustyai-fms",
        "image": main_image,
        "command": ["/bin/sh", "-c"],
        "args": [init_cmd],
        "volumeMounts": [
            {"name": "extra-packages", "mountPath": "/mnt/extra-packages"},
            {"name": "providers-dir", "mountPath": "/mnt/providers.d"},
        ],
    }
)
spec["initContainers"] = inits

# Main container: add volume mounts, PYTHONPATH, and postStart hook
for c in spec["containers"]:
    if c["name"] != "llama-stack":
        continue

    mounts = [m for m in c.get("volumeMounts", []) if m["name"] not in ("extra-packages", "providers-dir")]
    mounts += [
        {"name": "extra-packages", "mountPath": "/mnt/extra-packages"},
        {"name": "providers-dir", "mountPath": "/mnt/providers.d"},
    ]
    c["volumeMounts"] = mounts

    env = [e for e in c.get("env", []) if e["name"] != "PYTHONPATH"]
    env.append({"name": "PYTHONPATH", "value": "/mnt/extra-packages"})
    c["env"] = env

    lc = c.get("lifecycle", {})
    lc["postStart"] = {"exec": {"command": ["/bin/sh", "-c", post_start_cmd]}}
    c["lifecycle"] = lc
    break

apply_json(deploy)
print("  Deployment patched.")

# --- 3. Enable TrustyAI shields in agent-service ---
print("  Setting USE_TRUSTY_AI=true on agent-service...")
oc("set", "env", "deployment/self-service-agent-agent-service", "USE_TRUSTY_AI=true", "-n", NAMESPACE)
print("  agent-service updated.")
