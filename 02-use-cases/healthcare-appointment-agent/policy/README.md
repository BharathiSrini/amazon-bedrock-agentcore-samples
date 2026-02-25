# AgentCore Policy for Healthcare Appointment Agent

## Overview

This directory contains the implementation of Amazon Bedrock AgentCore Policy for the Healthcare Appointment Agent. It demonstrates patient-scoped access control using Cedar policies to ensure patients can only access their own healthcare data while allowing healthcare providers full access.

## Architecture

```
┌─────────────────┐
│   Patient       │  JWT Token with
│   (adult-001)   │  role="patient"
└────────┬────────┘  sub="adult-001"
         │
         ▼
┌─────────────────────────────────────┐
│  AgentCore Gateway                  │
│  + OAuth Authorization              │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  AgentCore Policy Engine            │
│  (Cedar Policies)                   │
│                                     │
│  ✓ PatientReadOnlyAccess           │
│  ✓ PatientAppointmentAccess        │
│  ✓ HealthcareProviderFullAccess    │
└────────┬────────────────────────────┘
         │
         ▼ ALLOW/DENY
┌─────────────────────────────────────┐
│  FHIR API Gateway                   │
│  (AWS HealthLake)                   │
└─────────────────────────────────────┘
```

## Policy Rules

### 1. Patient Read-Only Access

Patients can view their own healthcare information:

```cedar
permit(
  principal,
  action in [
    AgentCore::Action::"Target1___searchPatient",
    AgentCore::Action::"Target1___getPatient",
    AgentCore::Action::"Target1___getImmunization",
    AgentCore::Action::"Target1___getAppointment"
  ],
  resource == AgentCore::Gateway::"<gateway-arn>"
) when {
  principal.hasTag("role") &&
  principal.getTag("role") == "patient" &&
  context.input has patientId &&
  principal.hasTag("sub") &&
  context.input.patientId == principal.getTag("sub")
};
```

**Key Features:**
- Patients can search and view their own patient information
- Patients can view their immunization records
- Patients can view their appointments
- Access is restricted to data where `patientId` matches their authenticated identity (`sub` claim)

### 2. Patient Appointment Access

Patients can search for slots and book appointments:

```cedar
permit(
  principal,
  action in [
    AgentCore::Action::"Target1___searchSlot",
    AgentCore::Action::"Target1___createAppointment"
  ],
  resource == AgentCore::Gateway::"<gateway-arn>"
) when {
  principal.hasTag("role") &&
  principal.getTag("role") == "patient" &&
  context.input has patientId &&
  principal.hasTag("sub") &&
  context.input.patientId == principal.getTag("sub")
};
```

**Key Features:**
- Patients can search for available appointment slots
- Patients can create appointments for themselves
- Booking is restricted to their own patient ID

### 3. Healthcare Provider Full Access

Healthcare providers (doctors, nurses, admins) have unrestricted access:

```cedar
permit(
  principal,
  action,
  resource == AgentCore::Gateway::"<gateway-arn>"
) when {
  principal.hasTag("role") &&
  principal.getTag("role") in ["doctor", "nurse", "admin"]
};
```

**Key Features:**
- Full access to all tools
- Can view and manage any patient's data
- No patient ID restrictions

## Prerequisites

Before setting up policy, ensure you have:

1. Completed the main healthcare agent setup (see parent README.md)
2. Gateway created and configured with `setup_fhir_mcp.py`
3. Test data loaded into AWS HealthLake
4. Python dependencies installed
5. AWS credentials configured with permissions for:
   - `bedrock-agentcore:*`
   - `cognito-idp:DescribeUserPoolClient`

## Setup Instructions

### Step 1: Install Additional Dependencies

```bash
# Ensure you're in the healthcare-appointment-agent directory
cd 02-use-cases/healthcare-appointment-agent

# Activate your virtual environment
source ./.venv/bin/activate

# Install dependencies (if not already installed)
uv pip install -r requirements.txt
```

### Step 2: Create and Attach Policy Engine

Run the setup script with your gateway ID (from `setup_fhir_mcp.py` output):

```bash
python policy/setup_policy.py --gateway_id <your-gateway-id>
```

This script will:
1. Create a Policy Engine named "HealthcarePatientAccessPolicy"
2. Attach the Policy Engine to your Gateway
3. Create three Cedar policies:
   - `PatientReadOnlyAccess`
   - `PatientAppointmentAccess`
   - `HealthcareProviderFullAccess`
4. Save configuration to `policy/policy_config.json`

**Expected Output:**
```
🚀 Setting up AgentCore Policy for Healthcare Appointment Agent
======================================================================

📦 Loading configuration...
✅ Configuration loaded
   Region: us-east-1
   Gateway ID: abc123xyz
   Gateway ARN: arn:aws:bedrock-agentcore:us-east-1:123456789012:gateway/abc123xyz

🔧 Initializing AgentCore client...
✅ Client initialized

📝 Creating Policy Engine: HealthcarePatientAccessPolicy...
✅ Policy Engine created
   Engine ID: engine-123
   Engine ARN: arn:aws:bedrock-agentcore:us-east-1:123456789012:policy-engine/engine-123

📝 Attaching Policy Engine to Gateway...
✅ Policy Engine attached to Gateway

📝 Creating patient read-only policy...
✅ Policy created: policy-read-123

📝 Creating patient appointment booking policy...
✅ Policy created: policy-appt-456

📝 Creating healthcare provider full access policy...
✅ Policy created: policy-provider-789

======================================================================
✅ POLICY SETUP COMPLETE!
======================================================================
Policy Engine ID: engine-123
Policy Engine Mode: ENFORCE

Policies Created: 3
   • PatientReadOnlyAccess - Patients can view their own data
   • PatientAppointmentAccess - Patients can book appointments
   • HealthcareProviderFullAccess - Providers have full access

🔒 Access control is now enforced on the gateway!
======================================================================
```

### Step 3: Test Policy Enforcement

Run the test script to verify policies are working:

```bash
python policy/test_policy.py
```

This will run three test scenarios:
1. **Patient Access Test** - Verify patients can only access their own data
2. **Provider Access Test** - Verify providers can access all patient data
3. **Appointment Booking Test** - Verify patients can book appointments for themselves

### Step 4: Run the Agent with Policy Enforcement

Now run the agent as usual - policies will be enforced automatically:

```bash
python strands_agent.py --gateway_id <your-gateway-id>
```

Try these prompts to test policy enforcement:

**As a Patient (adult-patient-001):**
- ✅ "Show me my immunization records" (ALLOWED)
- ✅ "Book an appointment for me" (ALLOWED)
- ❌ "Show immunization records for pediatric-patient-001" (DENIED by policy)

## Policy Configuration

The `policy_config.json` file stores your policy setup:

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

## Modifying Policies

### Change Policy Mode

To switch between LOG_ONLY (testing) and ENFORCE (production):

```python
import boto3

client = boto3.client('bedrock-agentcore', region_name='us-east-1')

# Switch to LOG_ONLY mode (policies log but don't block)
client.update_policy_engine(
    policyEngineIdentifier='<engine-id>',
    mode='LOG_ONLY'
)

# Switch to ENFORCE mode (policies actively block requests)
client.update_policy_engine(
    policyEngineIdentifier='<engine-id>',
    mode='ENFORCE'
)
```

### Add Custom Policies

You can add additional policies for specific use cases:

```python
# Example: Restrict appointment booking to business hours
policy_statement = '''
permit(
  principal,
  action == AgentCore::Action::"Target1___createAppointment",
  resource == AgentCore::Gateway::"<gateway-arn>"
) when {
  principal.getTag("role") == "patient" &&
  context.input.appointmentTime >= "08:00" &&
  context.input.appointmentTime <= "17:00"
};
'''

client.create_policy(
    policyEngineIdentifier='<engine-id>',
    name='BusinessHoursOnly',
    description='Restrict appointments to business hours',
    policyStatement=policy_statement
)
```

## Monitoring and Debugging

### CloudWatch Logs

Policy decisions are logged to CloudWatch:

1. **Gateway Logs**: Request/response details with policy evaluation results
2. **Policy Engine Logs**: Detailed policy evaluation traces

### Common Issues

**Issue: All requests are denied**
- Verify Policy Engine is in ENFORCE mode (not LOG_ONLY)
- Check that policies are in ACTIVE status
- Confirm Gateway ARN in policies matches your gateway

**Issue: Patient can access other patients' data**
- Verify JWT token includes correct `sub` claim
- Check that `patientId` parameter is being passed correctly
- Review policy conditions for `context.input.patientId == principal.getTag("sub")`

**Issue: Provider access is blocked**
- Verify JWT token includes `role` claim with value "doctor", "nurse", or "admin"
- Check that HealthcareProviderFullAccess policy is active

## Cleanup

To remove policy enforcement:

```bash
# Detach policy engine from gateway
python policy/cleanup_policy.py --gateway_id <your-gateway-id>
```

Or manually:

```python
import boto3

client = boto3.client('bedrock-agentcore', region_name='us-east-1')

# Detach policy engine
client.update_gateway(
    gatewayIdentifier='<gateway-id>',
    policyEngineId=None
)

# Delete policies
client.delete_policy(policyEngineIdentifier='<engine-id>', policyId='<policy-id>')

# Delete policy engine
client.delete_policy_engine(policyEngineIdentifier='<engine-id>')
```

## Security Best Practices

1. **Always use ENFORCE mode in production** - LOG_ONLY is for testing only
2. **Validate JWT claims** - Ensure your OAuth provider includes required claims (role, sub)
3. **Principle of least privilege** - Grant minimum necessary permissions
4. **Regular audits** - Review CloudWatch logs for policy violations
5. **Test thoroughly** - Use test_policy.py to verify policies before production

## Advanced Policies

For production deployments, see the advanced policy examples that include:

### 1. Parent-Child Relationships
Allow parents to view and manage their children's healthcare appointments.

### 2. Staff Facility Scoping
Restrict staff to their assigned facilities and patient panels.

### 3. Read-Write Separation
Broad read access with restricted write operations.

### 4. PHI Data Minimization
Block access to highly sensitive identifiers (SSN, full card numbers).

### 5. Appointment Abuse Prevention
Prevent patients from booking too many appointments or rapid cancellations.

### 6. Time-of-Day Restrictions
Limit operations to clinic hours and allowed regions.

### Setup Advanced Policies

```bash
# After basic policy setup, add advanced policies
python policy/setup_advanced_policies.py

# Review all available advanced policies
cat policy/advanced_policies.cedar

# Deploy Lambda interceptor for context enrichment
# See policy/lambda_interceptor_example.py
```

**Files:**
- `advanced_policies.cedar` - Complete set of production-ready Cedar policies
- `setup_advanced_policies.py` - Script to deploy advanced policies
- `lambda_interceptor_example.py` - Lambda function to enrich request context

**Requirements for Advanced Policies:**
1. Lambda interceptor deployed to enrich context with derived data
2. JWT tokens with additional claims (children, assignedFacilities, etc.)
3. DynamoDB tables for relationships and rate limiting
4. Testing in LOG_ONLY mode before production

## Additional Resources

- [Amazon Bedrock AgentCore Policy Documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html)
- [Cedar Policy Language](https://docs.cedarpolicy.com/)
- [Policy Tutorial](../../../01-tutorials/08-AgentCore-policy/)
- [Example Cedar Policies](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/example-policies.html)
- [Advanced Policies Guide](advanced_policies.cedar)
- [Lambda Interceptor Example](lambda_interceptor_example.py)

## Support

For issues or questions:
1. Check CloudWatch logs for policy evaluation details
2. Review the main healthcare agent README.md
3. Refer to the AgentCore Policy tutorial in `01-tutorials/08-AgentCore-policy/`
4. See advanced_policies.cedar for production-ready policy patterns
