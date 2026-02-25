# Advanced Cedar Policies for Healthcare Agent

## Overview

This document describes production-ready Cedar policies for healthcare appointment scheduling, including parent-child relationships, facility scoping, PHI minimization, abuse prevention, and time-based restrictions.

## Policy Categories

### 1. Parent-Child Relationship Policies

**Use Case:** Parents need to view and manage healthcare appointments for their children.

**Implementation:** Lambda interceptor populates `context.identity.children` from database.

**Cedar Policy:**
```cedar
permit(
  principal,
  action in [
    "schedule:getAppointments",
    "schedule:createAppointment"
  ],
  resource
) when {
  principal.role == "patient" &&
  (
    context.input.patientId == context.identity.sub ||
    context.input.patientId in context.identity.children
  )
};
```

**JWT Token Requirements:**
- `sub`: Parent's patient ID
- `role`: "patient"
- `children`: Array of child patient IDs (populated by Lambda)

**Example:**
```json
{
  "sub": "adult-patient-001",
  "role": "patient",
  "children": ["pediatric-patient-001", "pediatric-patient-002"]
}
```

---

### 2. Staff Facility and Panel Scoping

**Use Case:** Schedulers and clinicians should only access patients assigned to their facility and panel.

**Implementation:** JWT token includes assigned facilities and patients.

**Cedar Policy:**
```cedar
permit(
  principal,
  action in [
    "schedule:getAppointments",
    "schedule:createAppointment"
  ],
  resource
) when {
  principal.role in ["scheduler", "clinician"] &&
  context.input.facilityId in principal.assignedFacilities &&
  context.input.patientId in principal.assignedPatients
};
```

**JWT Token Requirements:**
- `role`: "scheduler" or "clinician"
- `assignedFacilities`: Array of facility IDs
- `assignedPatients`: Array of patient IDs

**Example:**
```json
{
  "sub": "staff-123",
  "role": "scheduler",
  "assignedFacilities": ["facility-001", "facility-002"],
  "assignedPatients": ["patient-001", "patient-002", "patient-003"]
}
```

---

### 3. Read vs Write Separation

**Use Case:** Allow broad read access but restrict write operations to authorized staff.

**3a. Broad Read Access:**
```cedar
permit(
  principal,
  action in [
    "schedule:getAvailableSlots",
    "schedule:getAppointmentDetails"
  ],
  resource
) when {
  principal.isAuthenticated == true &&
  (
    principal.role != "patient" ||
    context.input.patientId == context.identity.sub
  )
};
```

**3b. Restricted Write Access:**
```cedar
permit(
  principal,
  action in [
    "schedule:createAppointment",
    "schedule:rescheduleAppointment"
  ],
  resource
) when {
  principal.role in ["scheduler", "clinician"] &&
  context.input.facilityId in principal.assignedFacilities
};
```

**3c. Block Clinical Data Mutations:**
```cedar
forbid(
  principal,
  action in [
    "ehr:updateDiagnosis",
    "ehr:updateMedication",
    "ehr:writeClinicalNote"
  ],
  resource
) when {
  true  // Block for all users - this is a scheduling agent only
};
```

---

### 4. PHI Data Access Minimization

**Use Case:** Restrict access to highly sensitive PHI based on role and necessity.

**4a. Restrict High-PHI Tools:**
```cedar
permit(
  principal,
  action in [
    "ehr:getFullClinicalHistory",
    "billing:getPaymentInstruments"
  ],
  resource
) when {
  principal.role == "backoffice"
};
```

**4b. Forbid Sensitive Identifiers:**
```cedar
forbid(
  principal,
  action in [
    "identity:getFullSSN",
    "billing:getFullCardNumber"
  ],
  resource
) when {
  true  // No one should access full identifiers through this agent
};
```

**Best Practices:**
- Use masked versions (last 4 digits) for display
- Log all access to sensitive data
- Implement field-level filtering in tools
- Regular audits of PHI access patterns

---

### 5. Risk and Abuse Controls

**Use Case:** Prevent appointment abuse, no-shows, and resource waste.

**5a. Limit Appointments Per Specialty:**
```cedar
forbid(
  principal,
  action == "schedule:createAppointment",
  resource
) when {
  principal.role in ["patient", "scheduler"] &&
  context.input.patientId == context.identity.sub &&
  context.derived.upcomingAppointmentsInSpecialty >= 3
};
```

**5b. Require Staff for Same-Day Cancellations:**
```cedar
forbid(
  principal,
  action == "schedule:cancelAppointment",
  resource
) when {
  context.derived.isSameDay == true &&
  principal.role not in ["scheduler", "clinician"]
};
```

**5c. Protect Surgery/Procedure Slots:**
```cedar
forbid(
  principal,
  action in [
    "schedule:cancelAppointment",
    "schedule:rescheduleAppointment"
  ],
  resource
) when {
  context.derived.isSurgeryOrProcedure == true &&
  principal.role not in ["scheduler", "clinician"] &&
  context.approvals.supervisorApproved != true
};
```

**5d. Rate Limiting:**
```cedar
forbid(
  principal,
  action == "schedule:createAppointment",
  resource
) when {
  context.rateLimit.appointmentsCreatedInLastHour >= 5 &&
  principal.role == "patient"
};
```

**Lambda Interceptor Requirements:**
- Calculate `context.derived.upcomingAppointmentsInSpecialty`
- Set `context.derived.isSameDay` flag
- Set `context.derived.isSurgeryOrProcedure` flag
- Track `context.rateLimit.appointmentsCreatedInLastHour`

---

### 6. Time-of-Day and Region Restrictions

**Use Case:** Ensure operations happen during appropriate hours and in allowed regions.

**6a. Clinic Hours Restriction:**
```cedar
permit(
  principal,
  action == "schedule:rescheduleAppointment",
  resource
) when {
  principal.role in ["patient", "scheduler", "clinician"] &&
  context.geo.region in ["US-WEST", "US-EAST"] &&
  context.time.hour >= 7 &&
  context.time.hour <= 19
};
```

**6b. Forbid After-Hours Operations:**
```cedar
forbid(
  principal,
  action == "schedule:rescheduleAppointment",
  resource
) when {
  context.time.hour < 7 ||
  context.time.hour > 19
};
```

**6c. Emergency Access Override:**
```cedar
permit(
  principal,
  action in [
    "schedule:rescheduleAppointment",
    "schedule:createAppointment"
  ],
  resource
) when {
  principal.role in ["admin", "onCallStaff"] &&
  context.emergency.isEmergencyAccess == true
};
```

**6d. Data Residency Compliance:**
```cedar
forbid(
  principal,
  action in [
    "schedule:getPatient",
    "schedule:getAppointment"
  ],
  resource
) when {
  context.input.patientRegion != principal.operatingRegion &&
  principal.crossRegionAccess != true
};
```

**Lambda Interceptor Requirements:**
- Populate `context.time.hour` from current time
- Set `context.geo.region` from IP geolocation
- Add `context.emergency.isEmergencyAccess` flag

---

## Lambda Interceptor Implementation

### Required Context Enrichment

The Lambda interceptor must populate the following context fields:

```python
{
  "identity": {
    "sub": "adult-patient-001",
    "children": ["pediatric-patient-001"],
    "assignedFacilities": ["facility-123"],
    "assignedPatients": ["patient-001", "patient-002"]
  },
  "derived": {
    "upcomingAppointmentsInSpecialty": 2,
    "totalUpcomingAppointments": 5,
    "isSameDay": false,
    "isSurgeryOrProcedure": false,
    "recentCancellations": 1,
    "noShowCount": 0
  },
  "time": {
    "hour": 14,
    "minute": 30,
    "dayOfWeek": "Monday",
    "isWeekend": false
  },
  "geo": {
    "region": "US-EAST",
    "country": "US"
  },
  "rateLimit": {
    "appointmentsCreatedInLastHour": 2,
    "appointmentsCreatedToday": 5,
    "cancellationsInLastWeek": 1
  }
}
```

### Database Schema Requirements

**patient-relationships table:**
```json
{
  "userId": "adult-patient-001",
  "children": ["pediatric-patient-001"],
  "assignedFacilities": ["facility-123"],
  "assignedPatients": ["patient-001"]
}
```

**appointment-history table:**
```json
{
  "patientId": "adult-patient-001",
  "appointmentDate": "2024-03-15T10:00:00Z",
  "specialty": "pediatrics",
  "appointmentStatus": "scheduled",
  "appointmentType": "routine"
}
```

**rate-limits table:**
```json
{
  "userId": "adult-patient-001",
  "recentActions": [
    {
      "action": "createAppointment",
      "timestamp": "2024-03-15T10:00:00Z"
    }
  ]
}
```

---

## Deployment Guide

### Step 1: Deploy Lambda Interceptor

```bash
# Package Lambda function
cd policy
zip lambda_interceptor.zip lambda_interceptor_example.py

# Deploy to AWS Lambda
aws lambda create-function \
  --function-name healthcare-policy-interceptor \
  --runtime python3.12 \
  --handler lambda_interceptor_example.lambda_handler \
  --zip-file fileb://lambda_interceptor.zip \
  --role arn:aws:iam::ACCOUNT:role/lambda-execution-role
```

### Step 2: Create DynamoDB Tables

```bash
# Create patient relationships table
aws dynamodb create-table \
  --table-name patient-relationships \
  --attribute-definitions AttributeName=userId,AttributeType=S \
  --key-schema AttributeName=userId,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST

# Create appointment history table
aws dynamodb create-table \
  --table-name appointment-history \
  --attribute-definitions \
    AttributeName=patientId,AttributeType=S \
    AttributeName=appointmentDate,AttributeType=S \
  --key-schema \
    AttributeName=patientId,KeyType=HASH \
    AttributeName=appointmentDate,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST

# Create rate limits table
aws dynamodb create-table \
  --table-name rate-limits \
  --attribute-definitions AttributeName=userId,AttributeType=S \
  --key-schema AttributeName=userId,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST
```

### Step 3: Configure Gateway Interceptor

```python
import boto3

client = boto3.client('bedrock-agentcore')

# Attach Lambda interceptor to gateway
client.update_gateway(
    gatewayIdentifier='<gateway-id>',
    interceptorConfiguration={
        'lambdaArn': 'arn:aws:lambda:us-east-1:ACCOUNT:function:healthcare-policy-interceptor'
    }
)
```

### Step 4: Deploy Advanced Policies

```bash
python policy/setup_advanced_policies.py
```

### Step 5: Test in LOG_ONLY Mode

```python
# Switch to LOG_ONLY mode for testing
client.update_policy_engine(
    policyEngineIdentifier='<engine-id>',
    mode='LOG_ONLY'
)

# Run tests
python policy/test_policy.py

# Review CloudWatch logs for policy evaluation results
```

### Step 6: Enable ENFORCE Mode

```python
# After testing, switch to ENFORCE mode
client.update_policy_engine(
    policyEngineIdentifier='<engine-id>',
    mode='ENFORCE'
)
```

---

## Testing Scenarios

### Test 1: Parent-Child Access
```python
# Parent accessing child's data - SHOULD SUCCEED
jwt_token = {
    "sub": "adult-patient-001",
    "role": "patient",
    "children": ["pediatric-patient-001"]
}
request = {
    "action": "getAppointment",
    "patientId": "pediatric-patient-001"
}
# Expected: ALLOW
```

### Test 2: Staff Facility Scoping
```python
# Staff accessing patient outside their panel - SHOULD FAIL
jwt_token = {
    "sub": "staff-123",
    "role": "scheduler",
    "assignedPatients": ["patient-001", "patient-002"]
}
request = {
    "action": "getAppointment",
    "patientId": "patient-999"  # Not in assigned panel
}
# Expected: DENY
```

### Test 3: Appointment Abuse Prevention
```python
# Patient with 3+ appointments trying to book another - SHOULD FAIL
context = {
    "derived": {
        "upcomingAppointmentsInSpecialty": 3
    }
}
request = {
    "action": "createAppointment",
    "specialty": "pediatrics"
}
# Expected: DENY
```

### Test 4: Time Restriction
```python
# Rescheduling outside clinic hours - SHOULD FAIL
context = {
    "time": {
        "hour": 20  # 8 PM
    }
}
request = {
    "action": "rescheduleAppointment"
}
# Expected: DENY
```

---

## Monitoring and Observability

### CloudWatch Metrics

Monitor these key metrics:
- Policy evaluation latency
- ALLOW vs DENY ratio
- Policy evaluation errors
- Lambda interceptor execution time

### CloudWatch Logs

Review logs for:
- Policy evaluation traces
- Context enrichment data
- Failed policy evaluations
- Abuse detection triggers

### Alerts

Set up alerts for:
- High DENY rate (potential misconfiguration)
- Lambda interceptor failures
- Unusual access patterns
- Rate limit violations

---

## Best Practices

1. **Start Simple**: Deploy basic policies first, add advanced policies incrementally
2. **Test Thoroughly**: Use LOG_ONLY mode extensively before ENFORCE
3. **Monitor Closely**: Watch CloudWatch logs for false positives/negatives
4. **Document Claims**: Maintain clear documentation of required JWT claims
5. **Version Control**: Keep Cedar policies in version control
6. **Regular Audits**: Review policy effectiveness and access patterns
7. **Performance**: Monitor Lambda interceptor latency
8. **Fallback**: Have a plan to quickly disable policies if needed

---

## Troubleshooting

### Issue: All requests denied after adding advanced policies

**Solution:**
- Check Lambda interceptor is deployed and attached
- Verify JWT tokens include required claims
- Review CloudWatch logs for missing context fields
- Test in LOG_ONLY mode first

### Issue: Parent cannot access child's data

**Solution:**
- Verify `children` claim is populated in JWT
- Check Lambda interceptor is enriching context.identity.children
- Ensure patientId matches child ID exactly

### Issue: Staff can access patients outside their panel

**Solution:**
- Verify `assignedPatients` claim in JWT
- Check policy uses `in` operator correctly
- Review Lambda interceptor logic for staff assignments

### Issue: Time restrictions not working

**Solution:**
- Verify Lambda interceptor populates context.time.hour
- Check timezone handling (use UTC consistently)
- Test with different hours to verify boundaries

---

## Additional Resources

- [Cedar Policy Language Reference](https://docs.cedarpolicy.com/)
- [AgentCore Policy Documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html)
- [Lambda Interceptor Example](lambda_interceptor_example.py)
- [Advanced Policies Cedar File](advanced_policies.cedar)
- [Basic Policy Setup](README.md)
