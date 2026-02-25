// ============================================================================
// Advanced Cedar Policies for Healthcare Appointment Agent
// ============================================================================
// These policies demonstrate production-ready patterns for healthcare scheduling
// including parent-child relationships, facility scoping, PHI minimization,
// and abuse prevention controls.
//
// NOTE: Replace <gateway-arn> with your actual Gateway ARN
// ============================================================================


// ============================================================================
// 1. PARENT-CHILD RELATIONSHIP POLICIES
// ============================================================================
// Parents can view and manage appointments for their children
// Requires Lambda interceptor to populate context.identity.children from database

// Policy 1a: Parent can view their own and children's appointments
permit(
  principal,
  action in [
    AgentCore::Action::"Target1___getAppointment",
    AgentCore::Action::"Target1___searchPatient",
    AgentCore::Action::"Target1___getImmunization"
  ],
  resource == AgentCore::Gateway::"<gateway-arn>"
) when {
  principal.hasTag("role") &&
  principal.getTag("role") == "patient" &&
  context.input has patientId &&
  principal.hasTag("sub") &&
  (
    // Can access own data
    context.input.patientId == principal.getTag("sub") ||
    // Can access children's data (populated by Lambda interceptor)
    (
      principal.hasTag("children") &&
      context.input.patientId like principal.getTag("children")
    )
  )
};

// Policy 1b: Parent can book appointments for children
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
  (
    context.input.patientId == principal.getTag("sub") ||
    (
      principal.hasTag("children") &&
      context.input.patientId like principal.getTag("children")
    )
  )
};


// ============================================================================
// 2. STAFF FACILITY AND PANEL SCOPING
// ============================================================================
// Schedulers and clinicians can only act on patients assigned to their facility

// Policy 2a: Staff can manage appointments for assigned facility/patients
permit(
  principal,
  action in [
    AgentCore::Action::"Target1___getAppointment",
    AgentCore::Action::"Target1___createAppointment",
    AgentCore::Action::"Target1___searchSlot"
  ],
  resource == AgentCore::Gateway::"<gateway-arn>"
) when {
  principal.hasTag("role") &&
  principal.getTag("role") in ["scheduler", "clinician"] &&
  
  // Facility scoping - staff can only work with their assigned facilities
  context.input has facilityId &&
  principal.hasTag("assignedFacilities") &&
  context.input.facilityId like principal.getTag("assignedFacilities") &&
  
  // Patient panel scoping - staff can only work with assigned patients
  context.input has patientId &&
  principal.hasTag("assignedPatients") &&
  context.input.patientId like principal.getTag("assignedPatients")
};

// Policy 2b: Deny staff access to patients outside their panel
forbid(
  principal,
  action in [
    AgentCore::Action::"Target1___getAppointment",
    AgentCore::Action::"Target1___createAppointment",
    AgentCore::Action::"Target1___getPatient"
  ],
  resource == AgentCore::Gateway::"<gateway-arn>"
) when {
  principal.hasTag("role") &&
  principal.getTag("role") in ["scheduler", "clinician"] &&
  context.input has patientId &&
  principal.hasTag("assignedPatients") &&
  !(context.input.patientId like principal.getTag("assignedPatients"))
};


// ============================================================================
// 3. READ VS WRITE SEPARATION
// ============================================================================

// Policy 3a: Broad read access - any authenticated user can read scheduling info
permit(
  principal,
  action in [
    AgentCore::Action::"Target1___searchSlot",
    AgentCore::Action::"Target1___getAppointment"
  ],
  resource == AgentCore::Gateway::"<gateway-arn>"
) when {
  principal.hasTag("authenticated") &&
  principal.getTag("authenticated") == "true" &&
  (
    // Non-patients can read any scheduling data
    (
      principal.hasTag("role") &&
      principal.getTag("role") != "patient"
    ) ||
    // Patients can only read their own data
    (
      principal.hasTag("role") &&
      principal.getTag("role") == "patient" &&
      context.input has patientId &&
      principal.hasTag("sub") &&
      context.input.patientId == principal.getTag("sub")
    )
  )
};

// Policy 3b: Write operations limited to staff roles
permit(
  principal,
  action in [
    AgentCore::Action::"Target1___createAppointment"
  ],
  resource == AgentCore::Gateway::"<gateway-arn>"
) when {
  principal.hasTag("role") &&
  principal.getTag("role") in ["scheduler", "clinician", "admin"] &&
  context.input has facilityId &&
  principal.hasTag("assignedFacilities") &&
  context.input.facilityId like principal.getTag("assignedFacilities")
};

// Policy 3c: Explicitly deny clinical data mutations from this agent
// This agent is for scheduling only - no clinical record updates allowed
forbid(
  principal,
  action in [
    AgentCore::Action::"Target1___updateDiagnosis",
    AgentCore::Action::"Target1___updateMedication",
    AgentCore::Action::"Target1___writeClinicalNote",
    AgentCore::Action::"Target1___updateVitals"
  ],
  resource == AgentCore::Gateway::"<gateway-arn>"
) when {
  // Block for all users - this agent should not have these tools
  true
};


// ============================================================================
// 4. PHI DATA ACCESS MINIMIZATION
// ============================================================================
// Restrict access to highly sensitive PHI based on role

// Policy 4a: Only back-office roles can access full clinical history
permit(
  principal,
  action in [
    AgentCore::Action::"Target1___getFullClinicalHistory",
    AgentCore::Action::"Target1___getPaymentInstruments"
  ],
  resource == AgentCore::Gateway::"<gateway-arn>"
) when {
  principal.hasTag("role") &&
  principal.getTag("role") == "backoffice" &&
  principal.hasTag("clearanceLevel") &&
  principal.getTag("clearanceLevel") == "high"
};

// Policy 4b: Forbid access to highly sensitive identifiers
// No one should access full SSN or full card numbers through this agent
forbid(
  principal,
  action in [
    AgentCore::Action::"Target1___getFullSSN",
    AgentCore::Action::"Target1___getFullCardNumber",
    AgentCore::Action::"Target1___getDriversLicense"
  ],
  resource == AgentCore::Gateway::"<gateway-arn>"
) when {
  // Block for all users - use masked versions only
  true
};

// Policy 4c: Limit demographic data access for scheduling staff
permit(
  principal,
  action == AgentCore::Action::"Target1___getPatient",
  resource == AgentCore::Gateway::"<gateway-arn>"
) when {
  principal.hasTag("role") &&
  principal.getTag("role") in ["scheduler", "receptionist"] &&
  
  // Only allow access to basic demographic fields
  // (Implementation note: This requires field-level filtering in the tool)
  context.input has requestedFields &&
  context.input.requestedFields in ["name", "dateOfBirth", "contactInfo"]
};


// ============================================================================
// 5. RISK AND ABUSE CONTROLS ON SCHEDULING
// ============================================================================
// Prevent appointment abuse and ensure proper authorization for sensitive changes

// Policy 5a: Deny booking if patient has too many upcoming appointments
// Prevents appointment hoarding and no-show abuse
forbid(
  principal,
  action == AgentCore::Action::"Target1___createAppointment",
  resource == AgentCore::Gateway::"<gateway-arn>"
) when {
  principal.hasTag("role") &&
  principal.getTag("role") in ["patient", "scheduler"] &&
  context.input has patientId &&
  principal.hasTag("sub") &&
  context.input.patientId == principal.getTag("sub") &&
  
  // Check derived context from Lambda interceptor
  context.has("derived") &&
  context.derived has upcomingAppointmentsInSpecialty &&
  context.derived.upcomingAppointmentsInSpecialty >= 3
};

// Policy 5b: Require staff role for same-day cancellations
// Prevents last-minute cancellations that waste clinic resources
forbid(
  principal,
  action in [
    AgentCore::Action::"Target1___cancelAppointment"
  ],
  resource == AgentCore::Gateway::"<gateway-arn>"
) when {
  // Derived flags from Lambda interceptor
  context.has("derived") &&
  context.derived has isSameDay &&
  context.derived.isSameDay == true &&
  
  // Only staff can cancel same-day
  principal.hasTag("role") &&
  principal.getTag("role") not in ["scheduler", "clinician", "admin"]
};

// Policy 5c: Require senior staff for surgery/procedure changes
// High-value appointments need additional authorization
forbid(
  principal,
  action in [
    AgentCore::Action::"Target1___cancelAppointment",
    AgentCore::Action::"Target1___rescheduleAppointment"
  ],
  resource == AgentCore::Gateway::"<gateway-arn>"
) when {
  context.has("derived") &&
  context.derived has isSurgeryOrProcedure &&
  context.derived.isSurgeryOrProcedure == true &&
  
  // Require senior staff or admin
  principal.hasTag("role") &&
  principal.getTag("role") not in ["admin", "seniorClinician"] &&
  
  // Or require explicit approval flag
  !(
    context.has("approvals") &&
    context.approvals has supervisorApproved &&
    context.approvals.supervisorApproved == true
  )
};

// Policy 5d: Rate limiting - prevent rapid-fire appointment creation
forbid(
  principal,
  action == AgentCore::Action::"Target1___createAppointment",
  resource == AgentCore::Gateway::"<gateway-arn>"
) when {
  // Check rate limit from Lambda interceptor
  context.has("rateLimit") &&
  context.rateLimit has appointmentsCreatedInLastHour &&
  context.rateLimit.appointmentsCreatedInLastHour >= 5 &&
  
  // Apply to patients only, not staff
  principal.hasTag("role") &&
  principal.getTag("role") == "patient"
};


// ============================================================================
// 6. TIME-OF-DAY AND REGION RESTRICTIONS
// ============================================================================
// Ensure operations happen during appropriate hours and in allowed regions

// Policy 6a: Allow rescheduling only during clinic hours
permit(
  principal,
  action == AgentCore::Action::"Target1___rescheduleAppointment",
  resource == AgentCore::Gateway::"<gateway-arn>"
) when {
  principal.hasTag("role") &&
  principal.getTag("role") in ["patient", "scheduler", "clinician"] &&
  
  // Geographic restriction
  context.has("geo") &&
  context.geo has region &&
  context.geo.region in ["US-WEST", "US-EAST", "US-CENTRAL"] &&
  
  // Time restriction - clinic hours 07:00-19:00 local time
  context.has("time") &&
  context.time has hour &&
  context.time.hour >= 7 &&
  context.time.hour <= 19
};

// Policy 6b: Forbid rescheduling outside clinic hours
forbid(
  principal,
  action == AgentCore::Action::"Target1___rescheduleAppointment",
  resource == AgentCore::Gateway::"<gateway-arn>"
) when {
  context.has("time") &&
  context.time has hour &&
  (
    context.time.hour < 7 ||
    context.time.hour > 19
  )
};

// Policy 6c: Emergency access override for after-hours
// Allow admin and on-call staff to work after hours
permit(
  principal,
  action in [
    AgentCore::Action::"Target1___rescheduleAppointment",
    AgentCore::Action::"Target1___createAppointment",
    AgentCore::Action::"Target1___cancelAppointment"
  ],
  resource == AgentCore::Gateway::"<gateway-arn>"
) when {
  principal.hasTag("role") &&
  principal.getTag("role") in ["admin", "onCallStaff"] &&
  
  // Require emergency flag
  context.has("emergency") &&
  context.emergency has isEmergencyAccess &&
  context.emergency.isEmergencyAccess == true
};

// Policy 6d: Region-based data residency compliance
// Ensure patient data stays within their region
forbid(
  principal,
  action in [
    AgentCore::Action::"Target1___getPatient",
    AgentCore::Action::"Target1___getImmunization",
    AgentCore::Action::"Target1___getAppointment"
  ],
  resource == AgentCore::Gateway::"<gateway-arn>"
) when {
  // Patient's data region
  context.input has patientRegion &&
  
  // Staff's operating region
  principal.hasTag("operatingRegion") &&
  
  // Regions must match for data residency compliance
  context.input.patientRegion != principal.getTag("operatingRegion") &&
  
  // Unless staff has cross-region access
  !(
    principal.hasTag("crossRegionAccess") &&
    principal.getTag("crossRegionAccess") == "true"
  )
};


// ============================================================================
// 7. AUDIT AND COMPLIANCE POLICIES
// ============================================================================

// Policy 7a: Require audit logging for sensitive operations
permit(
  principal,
  action in [
    AgentCore::Action::"Target1___cancelAppointment",
    AgentCore::Action::"Target1___getFullClinicalHistory"
  ],
  resource == AgentCore::Gateway::"<gateway-arn>"
) when {
  principal.hasTag("role") &&
  principal.getTag("role") in ["admin", "backoffice"] &&
  
  // Require audit context
  context.has("audit") &&
  context.audit has reason &&
  context.audit has requestId
};

// Policy 7b: Forbid bulk data export for non-admin roles
forbid(
  principal,
  action in [
    AgentCore::Action::"Target1___exportPatientData",
    AgentCore::Action::"Target1___bulkExport"
  ],
  resource == AgentCore::Gateway::"<gateway-arn>"
) when {
  principal.hasTag("role") &&
  principal.getTag("role") not in ["admin", "dataGovernance"]
};


// ============================================================================
// IMPLEMENTATION NOTES
// ============================================================================
//
// 1. Lambda Interceptor Requirements:
//    - Populate context.identity.children from database
//    - Calculate context.derived.upcomingAppointmentsInSpecialty
//    - Set context.derived.isSameDay and isSurgeryOrProcedure flags
//    - Track context.rateLimit.appointmentsCreatedInLastHour
//    - Add context.time.hour and context.geo.region
//
// 2. JWT Token Claims Required:
//    - role: patient, scheduler, clinician, admin, etc.
//    - sub: unique user identifier
//    - children: comma-separated list of child patient IDs (for parents)
//    - assignedFacilities: comma-separated facility IDs (for staff)
//    - assignedPatients: comma-separated patient IDs (for staff)
//    - operatingRegion: geographic region (for data residency)
//
// 3. Testing:
//    - Test each policy in LOG_ONLY mode first
//    - Verify Lambda interceptor populates context correctly
//    - Monitor CloudWatch logs for policy evaluation traces
//    - Test edge cases (boundary hours, rate limits, etc.)
//
// 4. Deployment:
//    - Start with basic policies (1-3)
//    - Add advanced policies (4-7) incrementally
//    - Monitor for false positives/negatives
//    - Adjust thresholds based on real usage patterns
//
// ============================================================================
