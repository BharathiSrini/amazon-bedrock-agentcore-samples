"""
Setup script for advanced Cedar policies
This extends the basic policy setup with production-ready patterns
"""

import json
import sys
from pathlib import Path
import boto3
from botocore.exceptions import ClientError


def load_policy_config():
    """Load existing policy configuration"""
    config_file = Path(__file__).parent / "policy_config.json"
    
    if not config_file.exists():
        print("❌ Error: policy_config.json not found!")
        print("   Please run setup_policy.py first to create basic policies")
        sys.exit(1)
    
    with open(config_file, "r", encoding="utf-8") as f:
        return json.load(f)


def create_parent_child_policy(client, engine_id, gateway_arn):
    """Create policy for parent-child relationship access"""
    
    policy_statement = f'''
permit(
  principal,
  action in [
    AgentCore::Action::"Target1___getAppointment",
    AgentCore::Action::"Target1___searchPatient",
    AgentCore::Action::"Target1___getImmunization",
    AgentCore::Action::"Target1___createAppointment"
  ],
  resource == AgentCore::Gateway::"{gateway_arn}"
) when {{
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
}};
'''
    
    print("\n📝 Creating parent-child relationship policy...")
    print("   Allows parents to access their children's healthcare data")
    
    try:
        response = client.create_policy(
            policyEngineIdentifier=engine_id,
            name="ParentChildAccess",
            description="Allow parents to view and manage children's appointments",
            policyStatement=policy_statement
        )
        
        print(f"✅ Policy created: {response['policyId']}")
        return response['policyId']
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConflictException':
            print("⚠️  Policy already exists")
            return None
        raise


def create_staff_facility_policy(client, engine_id, gateway_arn):
    """Create policy for staff facility and panel scoping"""
    
    policy_statement = f'''
permit(
  principal,
  action in [
    AgentCore::Action::"Target1___getAppointment",
    AgentCore::Action::"Target1___createAppointment",
    AgentCore::Action::"Target1___searchSlot"
  ],
  resource == AgentCore::Gateway::"{gateway_arn}"
) when {{
  principal.hasTag("role") &&
  principal.getTag("role") in ["scheduler", "clinician"] &&
  context.input has facilityId &&
  principal.hasTag("assignedFacilities") &&
  context.input.facilityId like principal.getTag("assignedFacilities") &&
  context.input has patientId &&
  principal.hasTag("assignedPatients") &&
  context.input.patientId like principal.getTag("assignedPatients")
}};
'''
    
    print("\n📝 Creating staff facility scoping policy...")
    print("   Restricts staff to their assigned facilities and patient panels")
    
    try:
        response = client.create_policy(
            policyEngineIdentifier=engine_id,
            name="StaffFacilityScoping",
            description="Limit staff access to assigned facilities and patients",
            policyStatement=policy_statement
        )
        
        print(f"✅ Policy created: {response['policyId']}")
        return response['policyId']
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConflictException':
            print("⚠️  Policy already exists")
            return None
        raise


def create_read_write_separation_policy(client, engine_id, gateway_arn):
    """Create policy for read vs write separation"""
    
    # Read policy
    read_policy = f'''
permit(
  principal,
  action in [
    AgentCore::Action::"Target1___searchSlot",
    AgentCore::Action::"Target1___getAppointment"
  ],
  resource == AgentCore::Gateway::"{gateway_arn}"
) when {{
  principal.hasTag("authenticated") &&
  principal.getTag("authenticated") == "true" &&
  (
    (
      principal.hasTag("role") &&
      principal.getTag("role") != "patient"
    ) ||
    (
      principal.hasTag("role") &&
      principal.getTag("role") == "patient" &&
      context.input has patientId &&
      principal.hasTag("sub") &&
      context.input.patientId == principal.getTag("sub")
    )
  )
}};
'''
    
    print("\n📝 Creating read-write separation policy...")
    print("   Broad read access, restricted write operations")
    
    try:
        response = client.create_policy(
            policyEngineIdentifier=engine_id,
            name="BroadReadAccess",
            description="Allow authenticated users to read scheduling data",
            policyStatement=read_policy
        )
        
        print(f"✅ Read policy created: {response['policyId']}")
        return response['policyId']
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConflictException':
            print("⚠️  Policy already exists")
            return None
        raise


def create_clinical_data_block_policy(client, engine_id, gateway_arn):
    """Create policy to block clinical data mutations"""
    
    policy_statement = f'''
forbid(
  principal,
  action in [
    AgentCore::Action::"Target1___updateDiagnosis",
    AgentCore::Action::"Target1___updateMedication",
    AgentCore::Action::"Target1___writeClinicalNote",
    AgentCore::Action::"Target1___updateVitals"
  ],
  resource == AgentCore::Gateway::"{gateway_arn}"
) when {{
  true
}};
'''
    
    print("\n📝 Creating clinical data mutation block policy...")
    print("   Prevents any clinical record updates through this agent")
    
    try:
        response = client.create_policy(
            policyEngineIdentifier=engine_id,
            name="BlockClinicalMutations",
            description="Forbid clinical data updates - scheduling agent only",
            policyStatement=policy_statement
        )
        
        print(f"✅ Policy created: {response['policyId']}")
        return response['policyId']
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConflictException':
            print("⚠️  Policy already exists")
            return None
        raise


def create_phi_minimization_policy(client, engine_id, gateway_arn):
    """Create policy for PHI data access minimization"""
    
    policy_statement = f'''
forbid(
  principal,
  action in [
    AgentCore::Action::"Target1___getFullSSN",
    AgentCore::Action::"Target1___getFullCardNumber",
    AgentCore::Action::"Target1___getDriversLicense"
  ],
  resource == AgentCore::Gateway::"{gateway_arn}"
) when {{
  true
}};
'''
    
    print("\n📝 Creating PHI minimization policy...")
    print("   Blocks access to highly sensitive identifiers")
    
    try:
        response = client.create_policy(
            policyEngineIdentifier=engine_id,
            name="PHIMinimization",
            description="Forbid access to full SSN, card numbers, and other sensitive IDs",
            policyStatement=policy_statement
        )
        
        print(f"✅ Policy created: {response['policyId']}")
        return response['policyId']
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConflictException':
            print("⚠️  Policy already exists")
            return None
        raise


def create_appointment_abuse_policy(client, engine_id, gateway_arn):
    """Create policy to prevent appointment abuse"""
    
    policy_statement = f'''
forbid(
  principal,
  action == AgentCore::Action::"Target1___createAppointment",
  resource == AgentCore::Gateway::"{gateway_arn}"
) when {{
  principal.hasTag("role") &&
  principal.getTag("role") in ["patient", "scheduler"] &&
  context.input has patientId &&
  principal.hasTag("sub") &&
  context.input.patientId == principal.getTag("sub") &&
  context.has("derived") &&
  context.derived has upcomingAppointmentsInSpecialty &&
  context.derived.upcomingAppointmentsInSpecialty >= 3
}};
'''
    
    print("\n📝 Creating appointment abuse prevention policy...")
    print("   Prevents patients from booking too many appointments in same specialty")
    print("   ⚠️  Requires Lambda interceptor to populate context.derived")
    
    try:
        response = client.create_policy(
            policyEngineIdentifier=engine_id,
            name="PreventAppointmentAbuse",
            description="Deny booking if patient has 3+ upcoming appointments in specialty",
            policyStatement=policy_statement
        )
        
        print(f"✅ Policy created: {response['policyId']}")
        return response['policyId']
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConflictException':
            print("⚠️  Policy already exists")
            return None
        raise


def create_time_restriction_policy(client, engine_id, gateway_arn):
    """Create policy for time-of-day restrictions"""
    
    policy_statement = f'''
forbid(
  principal,
  action == AgentCore::Action::"Target1___rescheduleAppointment",
  resource == AgentCore::Gateway::"{gateway_arn}"
) when {{
  context.has("time") &&
  context.time has hour &&
  (
    context.time.hour < 7 ||
    context.time.hour > 19
  )
}};
'''
    
    print("\n📝 Creating time-of-day restriction policy...")
    print("   Prevents rescheduling outside clinic hours (7 AM - 7 PM)")
    print("   ⚠️  Requires Lambda interceptor to populate context.time")
    
    try:
        response = client.create_policy(
            policyEngineIdentifier=engine_id,
            name="ClinicHoursOnly",
            description="Forbid rescheduling outside clinic hours",
            policyStatement=policy_statement
        )
        
        print(f"✅ Policy created: {response['policyId']}")
        return response['policyId']
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConflictException':
            print("⚠️  Policy already exists")
            return None
        raise


def setup_advanced_policies():
    """Main setup function for advanced policies"""
    print("=" * 70)
    print("🚀 Setting up Advanced Cedar Policies")
    print("=" * 70)
    
    # Load existing configuration
    print("\n📦 Loading policy configuration...")
    config = load_policy_config()
    
    region = config.get("region", "us-east-1")
    engine_id = config["policy_engine"]["engine_id"]
    gateway_arn = config.get("gateway_arn")
    
    print(f"✅ Configuration loaded")
    print(f"   Region: {region}")
    print(f"   Policy Engine: {engine_id}")
    print(f"   Gateway ARN: {gateway_arn}")
    
    # Initialize client
    print("\n🔧 Initializing AgentCore client...")
    client = boto3.client('bedrock-agentcore', region_name=region)
    print("✅ Client initialized")
    
    # Create advanced policies
    advanced_policy_ids = {}
    
    advanced_policy_ids['parent_child'] = create_parent_child_policy(
        client, engine_id, gateway_arn
    )
    
    advanced_policy_ids['staff_facility'] = create_staff_facility_policy(
        client, engine_id, gateway_arn
    )
    
    advanced_policy_ids['read_write_separation'] = create_read_write_separation_policy(
        client, engine_id, gateway_arn
    )
    
    advanced_policy_ids['clinical_block'] = create_clinical_data_block_policy(
        client, engine_id, gateway_arn
    )
    
    advanced_policy_ids['phi_minimization'] = create_phi_minimization_policy(
        client, engine_id, gateway_arn
    )
    
    advanced_policy_ids['appointment_abuse'] = create_appointment_abuse_policy(
        client, engine_id, gateway_arn
    )
    
    advanced_policy_ids['time_restriction'] = create_time_restriction_policy(
        client, engine_id, gateway_arn
    )
    
    # Update configuration file
    config['policies']['advanced'] = {
        k: v for k, v in advanced_policy_ids.items() if v is not None
    }
    
    config_file = Path(__file__).parent / "policy_config.json"
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    
    print("\n" + "=" * 70)
    print("✅ ADVANCED POLICIES SETUP COMPLETE!")
    print("=" * 70)
    print(f"Advanced Policies Created: {len([v for v in advanced_policy_ids.values() if v])}")
    print("\n📋 Policies:")
    print("   • ParentChildAccess - Parents can manage children's appointments")
    print("   • StaffFacilityScoping - Staff limited to assigned facilities")
    print("   • BroadReadAccess - Read-only access for authenticated users")
    print("   • BlockClinicalMutations - Prevent clinical data updates")
    print("   • PHIMinimization - Block access to sensitive identifiers")
    print("   • PreventAppointmentAbuse - Limit appointments per specialty")
    print("   • ClinicHoursOnly - Restrict operations to clinic hours")
    
    print("\n⚠️  IMPORTANT NOTES:")
    print("   1. Some policies require Lambda interceptor for context enrichment")
    print("   2. See lambda_interceptor_example.py for implementation")
    print("   3. JWT tokens must include required claims (role, sub, children, etc.)")
    print("   4. Test policies in LOG_ONLY mode before enforcing")
    
    print("\n📚 Next Steps:")
    print("   1. Review advanced_policies.cedar for all available policies")
    print("   2. Deploy Lambda interceptor (lambda_interceptor_example.py)")
    print("   3. Configure JWT token claims in Cognito")
    print("   4. Test with test_advanced_policies.py")
    print("=" * 70)


if __name__ == "__main__":
    setup_advanced_policies()
