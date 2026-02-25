# Quick Start: Add Policy to Healthcare Agent

## Prerequisites

✅ Healthcare agent already set up and working
✅ Gateway created with `setup_fhir_mcp.py`
✅ Test data loaded into HealthLake
✅ Virtual environment activated

## 3-Step Setup

### Step 1: Create Policy Engine (2 minutes)

```bash
python policy/setup_policy.py --gateway_id <your-gateway-id>
```

**What this does:**
- Creates a Policy Engine named "HealthcarePatientAccessPolicy"
- Attaches it to your Gateway
- Creates 3 Cedar policies for patient and provider access
- Saves configuration to `policy/policy_config.json`

**Expected output:**
```
✅ POLICY SETUP COMPLETE!
Policy Engine ID: engine-123
Policies Created: 3
   • PatientReadOnlyAccess
   • PatientAppointmentAccess
   • HealthcareProviderFullAccess
🔒 Access control is now enforced on the gateway!
```

### Step 2: Test Policy Enforcement (1 minute)

```bash
python policy/test_policy.py
```

**What this tests:**
- ✅ Patient can access their own data
- ❌ Patient cannot access other patients' data
- ✅ Healthcare providers can access all data

### Step 3: Run Agent with Policy (same as before)

```bash
python strands_agent.py --gateway_id <your-gateway-id>
```

**Try these prompts:**
- ✅ "Show me my immunization records" (works - own data)
- ❌ "Show records for pediatric-patient-001" (blocked by policy)

## That's It!

Your healthcare agent now has patient-scoped access control. Patients can only access their own data, while healthcare providers have full access.

## Remove Policy (Optional)

```bash
python policy/cleanup_policy.py --gateway_id <your-gateway-id>
```

## What Changed?

**Before Policy:**
- All authenticated users could access any patient's data
- No access restrictions beyond OAuth authentication

**After Policy:**
- Patients can only access their own data (patientId must match their identity)
- Healthcare providers (doctor/nurse/admin) have full access
- All access decisions logged to CloudWatch

## Policy Rules

### Patient Access
```cedar
// Patients can only access data where patientId matches their identity
context.input.patientId == principal.getTag("sub")
```

### Provider Access
```cedar
// Providers with role doctor/nurse/admin have full access
principal.getTag("role") in ["doctor", "nurse", "admin"]
```

## Troubleshooting

**All requests denied?**
- Check that JWT token includes `role` and `sub` claims
- Verify Policy Engine is in ENFORCE mode
- Review CloudWatch logs for policy evaluation details

**Patient can access other patients' data?**
- Verify `patientId` parameter is being passed correctly
- Check that JWT `sub` claim matches patient ID

## Learn More

- Full documentation: [policy/README.md](README.md)
- Example policies: [policy/example_policies.cedar](example_policies.cedar)
- Advanced policies: [policy/advanced_policies.cedar](advanced_policies.cedar)
- Integration details: [policy/INTEGRATION_SUMMARY.md](INTEGRATION_SUMMARY.md)

## Advanced Policies (Optional)

For production deployments, add advanced policies:

```bash
python policy/setup_advanced_policies.py
```

This adds:
- Parent-child relationship access
- Staff facility scoping
- PHI data minimization
- Appointment abuse prevention
- Time-of-day restrictions

See [advanced_policies.cedar](advanced_policies.cedar) for all available policies.
