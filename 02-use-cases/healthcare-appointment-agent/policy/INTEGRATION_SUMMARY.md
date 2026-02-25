# AgentCore Policy Integration Summary

## What Was Added

This integration adds Amazon Bedrock AgentCore Policy to the Healthcare Appointment Agent, implementing patient-scoped access control using Cedar policies.

## Files Created

```
02-use-cases/healthcare-appointment-agent/policy/
├── README.md                    # Complete documentation for policy setup
├── setup_policy.py              # Script to create and attach policy engine
├── test_policy.py               # Script to test policy enforcement
├── cleanup_policy.py            # Script to remove policy enforcement
├── example_policies.cedar       # Cedar policy examples and templates
├── requirements.txt             # Python dependencies
├── INTEGRATION_SUMMARY.md       # This file
└── policy_config.json          # Generated configuration (after setup)
```

## Files Modified

- `02-use-cases/healthcare-appointment-agent/readme.md`
  - Fixed typo: "Uase case details" → "Use case details"
  - Added Policy to use case components
  - Added "Use case key Features" section
  - Added "Optional: Add Policy-Based Access Control" section
  - Updated cleanup instructions to include policy cleanup

## Policy Implementation

### Three Cedar Policies Created

1. **PatientReadOnlyAccess**
   - Patients can view their own patient information
   - Patients can view their immunization records
   - Patients can view their appointments
   - Enforces: `context.input.patientId == principal.getTag("sub")`

2. **PatientAppointmentAccess**
   - Patients can search for available appointment slots
   - Patients can create appointments for themselves
   - Enforces: `context.input.patientId == principal.getTag("sub")`

3. **HealthcareProviderFullAccess**
   - Healthcare providers (doctor, nurse, admin) have full access
   - No patient ID restrictions
   - Can view and manage any patient's data

### Key Security Features

- **Identity-Based Access Control**: Uses JWT token claims (role, sub)
- **Patient Data Isolation**: Patients can only access their own data
- **Provider Flexibility**: Healthcare providers have unrestricted access
- **Runtime Enforcement**: Policies are evaluated in real-time
- **Audit Trail**: All policy decisions logged to CloudWatch

## Usage Flow

### 1. Initial Setup (Without Policy)

```bash
# Standard healthcare agent setup
python init_env.py --cfn_name healthcare-cfn-stack --region us-east-1
python create_test_data.py
python setup_fhir_mcp.py --op_type Create --gateway_name MyGateway
python strands_agent.py --gateway_id <gateway-id>
```

### 2. Add Policy Enforcement (Optional)

```bash
# Add policy-based access control
python policy/setup_policy.py --gateway_id <gateway-id>

# Test policy enforcement
python policy/test_policy.py

# Run agent (same command, now with policy enforcement)
python strands_agent.py --gateway_id <gateway-id>
```

### 3. Cleanup

```bash
# Remove policy enforcement (optional)
python policy/cleanup_policy.py --gateway_id <gateway-id>

# Standard cleanup
python setup_fhir_mcp.py --op_type Delete --gateway_id <gateway-id>
aws cloudformation delete-stack --stack-name healthcare-cfn-stack
```

## Testing Scenarios

The `test_policy.py` script validates:

1. ✅ **Patient accessing own data** - Should succeed
2. ❌ **Patient accessing other's data** - Should fail (policy blocked)
3. ✅ **Provider accessing any data** - Should succeed
4. ✅ **Patient booking appointment for self** - Should succeed
5. ❌ **Patient booking appointment for others** - Should fail (policy blocked)

## Architecture Changes

### Before Policy Integration

```
Patient → Gateway (OAuth) → FHIR API → HealthLake
                                ↓
                        All authenticated requests allowed
```

### After Policy Integration

```
Patient → Gateway (OAuth) → Policy Engine (Cedar) → FHIR API → HealthLake
                                    ↓
                            ALLOW/DENY based on:
                            - principal.role
                            - principal.sub
                            - context.input.patientId
```

## Configuration Files

### policy_config.json (Generated)

```json
{
  "region": "us-east-1",
  "gateway_id": "abc123xyz",
  "gateway_arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:gateway/abc123xyz",
  "policy_engine": {
    "engine_id": "engine-123",
    "engine_arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:policy-engine/engine-123",
    "mode": "ENFORCE"
  },
  "policies": {
    "patient_read": "policy-read-123",
    "patient_appointment": "policy-appt-456",
    "provider_full_access": "policy-provider-789"
  }
}
```

## Benefits

1. **Security**: Enforces patient data isolation at the gateway level
2. **Compliance**: Helps meet HIPAA and healthcare data privacy requirements
3. **Flexibility**: Easy to add/modify policies without changing agent code
4. **Auditability**: All access decisions logged for compliance audits
5. **Optional**: Can be added/removed without affecting core agent functionality

## Next Steps

1. **Customize Policies**: Modify Cedar policies in `example_policies.cedar` for your use case
2. **Add Custom Claims**: Extend JWT tokens with additional claims (department, facility, etc.)
3. **Implement Role Hierarchy**: Create more granular roles (specialist, receptionist, etc.)
4. **Add Time-Based Policies**: Restrict access based on time of day or appointment schedules
5. **Monitor and Audit**: Set up CloudWatch dashboards for policy evaluation metrics

## References

- [AgentCore Policy Documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html)
- [Cedar Policy Language](https://docs.cedarpolicy.com/)
- [Policy Tutorial](../../../01-tutorials/08-AgentCore-policy/)
- [Healthcare Agent README](../readme.md)

## Support

For questions or issues:
1. Review the [policy/README.md](README.md) for detailed documentation
2. Check CloudWatch logs for policy evaluation details
3. Refer to the AgentCore Policy tutorial in `01-tutorials/08-AgentCore-policy/`
