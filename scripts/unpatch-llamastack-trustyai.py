#!/usr/bin/env python3
"""Reverts the llamastack Deployment and run-config ConfigMap to inline::llama-guard.

Usage: NAMESPACE=<ns> python3 scripts/unpatch-llamastack-trustyai.py
"""
import json
import os
import subprocess
import sys
import yaml

NAMESPACE = os.environ["NAMESPACE"]


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


# --- 1. Revert run-config ConfigMap ---
print("  Reverting run-config ConfigMap...")
cm = get_json("configmap/run-config")
cfg = yaml.safe_load(cm["data"]["config.yaml"])
cfg.pop("external_providers_dir", None)
cfg["providers"]["safety"] = [
    {
        "provider_id": "llama-guard",
        "provider_type": "inline::llama-guard",
        "config": {"excluded_categories": []},
    }
]
cm["data"]["config.yaml"] = yaml.dump(cfg, default_flow_style=False)
apply_json(cm)
print("  run-config reverted.")

# --- 2. Revert llamastack Deployment ---
print("  Reverting llamastack Deployment...")
deploy = get_json("deployment/llamastack")
spec = deploy["spec"]["template"]["spec"]

# Remove init container
inits = [ic for ic in spec.get("initContainers", []) if ic["name"] != "install-trustyai-fms"]
if inits:
    spec["initContainers"] = inits
elif "initContainers" in spec:
    del spec["initContainers"]

# Remove volumes
spec["volumes"] = [
    v for v in spec.get("volumes", []) if v["name"] not in ("extra-packages", "providers-dir")
]

# Remove volume mounts, PYTHONPATH, and postStart hook from main container
for c in spec["containers"]:
    if c["name"] != "llama-stack":
        continue

    c["volumeMounts"] = [
        m for m in c.get("volumeMounts", []) if m["name"] not in ("extra-packages", "providers-dir")
    ]

    c["env"] = [e for e in c.get("env", []) if e["name"] != "PYTHONPATH"]

    if "lifecycle" in c:
        c["lifecycle"].pop("postStart", None)
        if not c["lifecycle"]:
            del c["lifecycle"]
    break

apply_json(deploy)
print("  Deployment reverted.")

# --- 3. Remove TrustyAI shields flag from agent-service ---
print("  Removing USE_TRUSTY_AI from agent-service...")
oc("set", "env", "deployment/self-service-agent-agent-service", "USE_TRUSTY_AI-", "-n", NAMESPACE)
print("  agent-service updated.")
