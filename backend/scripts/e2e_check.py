"""Ad-hoc end-to-end check against a running Koverly backend."""

import json
import time
import urllib.error
import urllib.request

BASE = "http://localhost:8000/api/v1"


def call(method, path, body=None, token=None):
    headers = {}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


email = f"e2e_{int(time.time())}@example.com"
status, reg = call("POST", "/auth/register", {"email": email, "full_name": "E2E User", "password": "Passw0rd!123"})
assert status == 201, (status, reg)
token = reg["access_token"]
print("register:", status)

status, fam = call("POST", "/families", {"name": "E2E Family"}, token)
assert status == 201, (status, fam)
fid = fam["id"]
print("family:", status, fid)

status, policy = call("POST", f"/families/{fid}/policies", {
    "family_id": fid, "policy_type": "health", "insurer": "E2E Health",
    "policy_number": "E2E-001", "sum_insured": "750000", "premium": "15000",
    "premium_frequency": "yearly",
}, token)
assert status == 201, (status, policy)
print("policy:", status, policy["policy_number"])

status, dash = call("GET", f"/families/{fid}/dashboard", token=token)
assert status == 200, (status, dash)
print("dashboard:", status, "premium=", dash["total_annual_premium"], "health=", dash["total_health_coverage"])

status, cov = call("GET", f"/families/{fid}/coverage-map", token=token)
assert status == 200
print("coverage-map:", status, [(c["category"], c["policy_count"]) for c in cov["categories"] if c["policy_count"]])

status, intel = call("GET", f"/families/{fid}/insurance-intelligence", token=token)
assert status == 200
print("intelligence:", status, "items=", len(intel["items"]))

status, ans = call("POST", "/assistant/ask", {"family_id": fid, "question": "How much health insurance do I have?"}, token)
assert status == 200, (status, ans)
print("assistant:", status, "grounded=", ans["grounded"], "|", ans["answer"][:90])

status, cal = call("GET", f"/families/{fid}/calendar", token=token)
assert status == 200
print("calendar:", status, "events=", len(cal))

status, search = call("GET", f"/families/{fid}/search?q=e2e", token=token)
assert status == 200
print("search:", status, "results=", len(search["results"]))

status, sub = call("GET", f"/families/{fid}/subscription", token=token)
assert status == 200
print("subscription:", status, sub["plan"])

status, emer = call("GET", f"/families/{fid}/emergency", token=token)
assert status == 200
print("emergency:", status, "policies=", len(emer["policies"]), "steps=", len(emer["claim_instructions"]))

print("\nALL E2E CHECKS PASSED")
