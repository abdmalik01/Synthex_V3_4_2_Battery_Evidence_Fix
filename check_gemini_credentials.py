from __future__ import annotations

from dotenv import load_dotenv

from synthex_platform.providers import configured_gemini_credential_slots


load_dotenv(override=True)

slots = configured_gemini_credential_slots()
print("=== GEMINI CREDENTIAL CONFIGURATION ===")
print("External calls: 0")
print(f"Configured credential slots: {len(slots)}")
for slot in slots:
    print(f"- {slot}")
if len(slots) < 2:
    print("Failover status: PRIMARY ONLY")
else:
    print("Failover status: READY")
print("Credential values are never printed.")
