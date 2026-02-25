// Example Cedar Policies for Healthcare Appointment Agent
// These policies demonstrate patient-scoped access control

// ============================================================================
// Policy 1: Patient Read-Only Access
// ============================================================================
// Allows patients to read their own healthcare information
// Patients can view patient records, immunizations, and appointments
// Access is restricted to data where patientId matches their authenticated identity

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
  // Check that principal has a role tag
  principal.hasTag("role") &&
  principal.getTag("role") == "patient" &&
  
  // Check that input has patientId parameter
  context.input has patientId &&
  
  // Check that principal has sub (subject) tag
  principal.hasTag("sub") &&
  
  // Ensure patientId matches authenticated user's sub claim
  context.input.patientId == principal.getTag("sub")
};


// ============================================================================
// Policy 2: Patient Appointment Access
// ============================================================================
// Allows patients to search for appointment slots and book appointments
// Booking is restricted to their own patient ID

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


// ============================================================================
// Policy 3: Healthcare Provider Full Access
// ============================================================================
// Allows healthcare providers (doctors, nurses, admins) unrestricted access
// Providers can view and manage any patient's data

permit(
  principal,
  action,
  resource == AgentCore::Gateway::"<gateway-arn>"
) when {
  principal.hasTag("role") &&
  principal.getTag("role") in ["doctor", "nurse", "admin"]
};


// ============================================================================
// Additional Example Policies
// ============================================================================

// Example 4: Restrict appointment booking to business hours
// Uncomment and modify as needed
/*
permit(
  principal,
  action == AgentCore::Action::"Target1___createAppointment",
  resource == AgentCore::Gateway::"<gateway-arn>"
) when {
  principal.getTag("role") == "patient" &&
  context.input.patientId == principal.getTag("sub") &&
  
  // Assuming appointmentTime is in HH:MM format
  context.input has appointmentTime &&
  context.input.appointmentTime >= "08:00" &&
  context.input.appointmentTime <= "17:00"
};
*/

// Example 5: Restrict access by patient age (pediatric vs adult)
// Uncomment and modify as needed
/*
permit(
  principal,
  action == AgentCore::Action::"Target1___getImmunization",
  resource == AgentCore::Gateway::"<gateway-arn>"
) when {
  principal.getTag("role") == "patient" &&
  context.input.patientId == principal.getTag("sub") &&
  
  // Assuming patient type is in the context
  context.input has patientType &&
  context.input.patientType in ["adult", "pediatric"]
};
*/

// Example 6: Deny access to sensitive operations
// Uncomment and modify as needed
/*
forbid(
  principal,
  action == AgentCore::Action::"Target1___deleteAppointment",
  resource == AgentCore::Gateway::"<gateway-arn>"
) when {
  principal.getTag("role") == "patient"
};
*/

// Example 7: Allow access only from specific departments
// Uncomment and modify as needed
/*
permit(
  principal,
  action,
  resource == AgentCore::Gateway::"<gateway-arn>"
) when {
  principal.hasTag("department") &&
  principal.getTag("department") in ["pediatrics", "immunology", "family-medicine"]
};
*/

// ============================================================================
// Notes:
// ============================================================================
// 1. Replace <gateway-arn> with your actual Gateway ARN
// 2. JWT token must include required claims: role, sub, and any custom claims
// 3. Use hasTag() before getTag() to avoid errors
// 4. Test policies in LOG_ONLY mode before switching to ENFORCE
// 5. Monitor CloudWatch logs for policy evaluation results
