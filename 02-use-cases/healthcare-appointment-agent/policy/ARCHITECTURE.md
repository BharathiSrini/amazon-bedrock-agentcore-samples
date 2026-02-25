# Healthcare Agent Policy Architecture

## System Architecture with Policy Enforcement

```
┌─────────────────────────────────────────────────────────────────────┐
│                         User Layer                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────────┐              ┌──────────────────┐           │
│  │   Patient User   │              │  Provider User   │           │
│  │  (adult-001)     │              │  (doctor/nurse)  │           │
│  └────────┬─────────┘              └────────┬─────────┘           │
│           │                                  │                      │
│           │ JWT Token                        │ JWT Token            │
│           │ role: "patient"                  │ role: "doctor"       │
│           │ sub: "adult-001"                 │ sub: "provider-123"  │
│           │                                  │                      │
└───────────┼──────────────────────────────────┼──────────────────────┘
            │                                  │
            ▼                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    AgentCore Gateway Layer                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │         Amazon Bedrock AgentCore Gateway                      │ │
│  │         + OAuth Authorization (Cognito)                       │ │
│  │         + MCP Protocol Support                                │ │
│  └─────────────────────────┬─────────────────────────────────────┘ │
│                            │                                        │
│                            ▼                                        │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │         AgentCore Policy Engine (ENFORCE mode)                │ │
│  │                                                               │ │
│  │  ┌─────────────────────────────────────────────────────────┐ │ │
│  │  │  Policy 1: PatientReadOnlyAccess                        │ │ │
│  │  │  • Allow: searchPatient, getPatient, getImmunization    │ │ │
│  │  │  • Condition: patientId == principal.sub                │ │ │
│  │  └─────────────────────────────────────────────────────────┘ │ │
│  │                                                               │ │
│  │  ┌─────────────────────────────────────────────────────────┐ │ │
│  │  │  Policy 2: PatientAppointmentAccess                     │ │ │
│  │  │  • Allow: searchSlot, createAppointment                 │ │ │
│  │  │  • Condition: patientId == principal.sub                │ │ │
│  │  └─────────────────────────────────────────────────────────┘ │ │
│  │                                                               │ │
│  │  ┌─────────────────────────────────────────────────────────┐ │ │
│  │  │  Policy 3: HealthcareProviderFullAccess                 │ │ │
│  │  │  • Allow: All actions                                   │ │ │
│  │  │  • Condition: role in ["doctor", "nurse", "admin"]      │ │ │
│  │  └─────────────────────────────────────────────────────────┘ │ │
│  └───────────────────────┬───────────────────────────────────────┘ │
│                          │                                          │
│                          ▼                                          │
│                    ALLOW / DENY                                     │
│                          │                                          │
└──────────────────────────┼──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Backend Services Layer                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │              Amazon API Gateway                               │ │
│  │              + Lambda Functions                               │ │
│  └─────────────────────────┬─────────────────────────────────────┘ │
│                            │                                        │
│                            ▼                                        │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │              AWS HealthLake (FHIR R4)                         │ │
│  │              • Patient Records                                │ │
│  │              • Immunization Data                              │ │
│  │              • Appointment Schedules                          │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Request Flow Examples

### Example 1: Patient Accessing Own Data ✅

```
1. Patient (adult-001) sends request:
   "Get my immunization records"
   
2. Agent calls tool:
   getImmunization(patientId="adult-001")
   
3. Gateway receives request with JWT:
   {
     "role": "patient",
     "sub": "adult-001"
   }
   
4. Policy Engine evaluates:
   ✓ principal.getTag("role") == "patient"
   ✓ context.input.patientId == "adult-001"
   ✓ principal.getTag("sub") == "adult-001"
   ✓ "adult-001" == "adult-001" → MATCH!
   
5. Decision: ALLOW
   
6. Request forwarded to FHIR API
   
7. Response returned to patient
```

### Example 2: Patient Accessing Other's Data ❌

```
1. Patient (adult-001) sends request:
   "Get immunization records for pediatric-patient-001"
   
2. Agent calls tool:
   getImmunization(patientId="pediatric-patient-001")
   
3. Gateway receives request with JWT:
   {
     "role": "patient",
     "sub": "adult-001"
   }
   
4. Policy Engine evaluates:
   ✓ principal.getTag("role") == "patient"
   ✓ context.input.patientId == "pediatric-patient-001"
   ✓ principal.getTag("sub") == "adult-001"
   ✗ "pediatric-patient-001" != "adult-001" → NO MATCH!
   
5. Decision: DENY
   
6. Request blocked by policy
   
7. Error returned to patient: "Access Denied"
```

### Example 3: Provider Accessing Any Data ✅

```
1. Provider (doctor) sends request:
   "Get immunization records for pediatric-patient-001"
   
2. Agent calls tool:
   getImmunization(patientId="pediatric-patient-001")
   
3. Gateway receives request with JWT:
   {
     "role": "doctor",
     "sub": "provider-123"
   }
   
4. Policy Engine evaluates:
   ✓ principal.getTag("role") == "doctor"
   ✓ "doctor" in ["doctor", "nurse", "admin"] → MATCH!
   
5. Decision: ALLOW (no patientId check needed)
   
6. Request forwarded to FHIR API
   
7. Response returned to provider
```

## Policy Evaluation Logic

```
┌─────────────────────────────────────────────────────────────┐
│              Policy Evaluation Decision Tree                │
└─────────────────────────────────────────────────────────────┘

                    Incoming Request
                          │
                          ▼
              ┌───────────────────────┐
              │  Extract JWT Claims   │
              │  • role               │
              │  • sub                │
              └───────────┬───────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │  Extract Request      │
              │  Context              │
              │  • action             │
              │  • input.patientId    │
              └───────────┬───────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │  Is role = provider?  │
              └───────────┬───────────┘
                          │
                ┌─────────┴─────────┐
                │                   │
               YES                 NO
                │                   │
                ▼                   ▼
         ┌──────────┐      ┌──────────────────┐
         │  ALLOW   │      │  Is role =       │
         │  (Policy │      │  patient?        │
         │   3)     │      └────────┬─────────┘
         └──────────┘               │
                          ┌─────────┴─────────┐
                          │                   │
                         YES                 NO
                          │                   │
                          ▼                   ▼
                ┌──────────────────┐   ┌──────────┐
                │  Does patientId  │   │  DENY    │
                │  match sub?      │   │  (No     │
                └────────┬─────────┘   │  policy) │
                         │             └──────────┘
               ┌─────────┴─────────┐
               │                   │
              YES                 NO
               │                   │
               ▼                   ▼
        ┌──────────┐        ┌──────────┐
        │  ALLOW   │        │  DENY    │
        │  (Policy │        │  (Policy │
        │  1 or 2) │        │  1 or 2) │
        └──────────┘        └──────────┘
```

## Security Boundaries

```
┌─────────────────────────────────────────────────────────────┐
│                    Security Layers                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Layer 1: Authentication (OAuth/Cognito)                   │
│  ├─ Verifies user identity                                 │
│  ├─ Issues JWT token with claims                           │
│  └─ Ensures only authenticated users access gateway        │
│                                                             │
│  Layer 2: Authorization (AgentCore Policy)                 │
│  ├─ Evaluates Cedar policies                               │
│  ├─ Checks role-based permissions                          │
│  ├─ Validates patient-scoped access                        │
│  └─ Blocks unauthorized requests                           │
│                                                             │
│  Layer 3: Data Access (FHIR API)                           │
│  ├─ Executes allowed requests                              │
│  ├─ Returns only requested data                            │
│  └─ Maintains audit logs                                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Key Components

### 1. JWT Token Structure

```json
{
  "sub": "adult-patient-001",
  "role": "patient",
  "iss": "https://cognito-idp.us-east-1.amazonaws.com/...",
  "exp": 1234567890,
  "iat": 1234567890
}
```

### 2. Policy Engine Configuration

```json
{
  "name": "HealthcarePatientAccessPolicy",
  "mode": "ENFORCE",
  "policies": [
    "PatientReadOnlyAccess",
    "PatientAppointmentAccess",
    "HealthcareProviderFullAccess"
  ]
}
```

### 3. Request Context

```json
{
  "principal": {
    "role": "patient",
    "sub": "adult-patient-001"
  },
  "action": "Target1___getImmunization",
  "resource": "arn:aws:bedrock-agentcore:...:gateway/...",
  "context": {
    "input": {
      "patientId": "adult-patient-001"
    }
  }
}
```

## Monitoring and Observability

```
┌─────────────────────────────────────────────────────────────┐
│                    CloudWatch Logs                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Gateway Logs:                                             │
│  ├─ Request/response details                               │
│  ├─ Authentication status                                  │
│  └─ Policy evaluation results                              │
│                                                             │
│  Policy Engine Logs:                                       │
│  ├─ Policy evaluation traces                               │
│  ├─ ALLOW/DENY decisions                                   │
│  ├─ Condition evaluation details                           │
│  └─ Performance metrics                                    │
│                                                             │
│  FHIR API Logs:                                            │
│  ├─ Data access patterns                                   │
│  ├─ Query performance                                      │
│  └─ Error tracking                                         │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Benefits of This Architecture

1. **Defense in Depth**: Multiple security layers (auth + policy + data access)
2. **Patient Privacy**: Automatic enforcement of patient data isolation
3. **Provider Flexibility**: Healthcare providers maintain full access
4. **Audit Trail**: Complete logging of all access decisions
5. **Compliance Ready**: Supports HIPAA and healthcare data privacy requirements
6. **Scalable**: Policies evaluated in real-time without performance impact
7. **Maintainable**: Policies can be updated without changing agent code
