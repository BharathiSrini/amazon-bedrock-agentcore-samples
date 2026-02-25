"""
Setup script to create and attach Policy Engine to Healthcare Gateway
Implements patient-scoped access control for healthcare appointment agent
"""

import json
import sys
import time
from pathlib import Path
import boto3
from botocore.exceptions import ClientError


def load_config():
    """Load existing .env configuration"""
    config_file = Path(__file__).parent.parent / ".env"
    
    if not config_file.exists():
        print("❌ Error: .env file not found!")
        print(f"   Expected location: {config_file}")
        print("\n   Please run init_env.py first to set up the environment")
        sys.exit(1)
    
    config = {}
    with open(config_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                config[key.strip()] = value.strip().strip('"')
    
    return config


def create_policy_engine(client, gateway_arn, engine_name="HealthcarePatientAccessPolicy"):
    """Create a Policy Engine for the healthcare gateway"""
    print(f"\n📝 Creating Policy Engine: {engine_name}...")
    
    try:
        response = client.create_policy_engine(
            name=engine_name,
            description="Patient-scoped access control for healthcare appointment agent",
            mode="ENFORCE"  # Start in ENFORCE mode for production
        )
        
        engine_arn = response['policyEngineArn']
        engine_id = response['policyEngineId']
        
        print(f"✅ Policy Engine created")
        print(f"   Engine ID: {engine_id}")
        print(f"   Engine ARN: {engine_arn}")
        
        return engine_id, engine_arn
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConflictException':
            print(f"⚠️  Policy Engine '{engine_name}' already exists")
            # List engines to find the existing one
            response = client.list_policy_engines()
            for engine in response.get('items', []):
                if engine['name'] == engine_name:
                    return engine['policyEngineId'], engine['policyEngineArn']
        raise


def attach_policy_engine_to_gateway(client, gateway_id, engine_id):
    """Attach the Policy Engine to the Gateway"""
    print(f"\n📝 Attaching Policy Engine to Gateway...")
    
    try:
        client.update_gateway(
            gatewayIdentifier=gateway_id,
            policyEngineId=engine_id
        )
        
        print("✅ Policy Engine attached to Gateway")
        print("⏳ Waiting 10s for attachment to propagate...")
        time.sleep(10)
        
    except ClientError as e:
        print(f"❌ Error attaching Policy Engine: {e}")
        raise


def create_patient_read_policy(client, engine_id, gateway_arn):
    """Create Cedar policy for patient read-only access to their own data"""
    
    policy_statement = f'''
permit(
  principal,
  action in [
    AgentCore::Action::"Target1___searchPatient",
    AgentCore::Action::"Target1___getPatient",
    AgentCore::Action::"Target1___getImmunization",
    AgentCore::Action::"Target1___getAppointment"
  ],
  resource == AgentCore::Gateway::"{gateway_arn}"
) when {{
  principal.hasTag("role") &&
  principal.getTag("role") == "patient" &&
  context.input has patientId &&
  principal.hasTag("sub") &&
  context.input.patientId == principal.getTag("sub")
}};
'''
    
    print("\n📝 Creating patient read-only policy...")
    print("Policy allows patients to:")
    print("   • Search and view their own patient information")
    print("   • View their immunization records")
    print("   • View their appointments")
    print("   • Only when patientId matches their authenticated identity (sub)")
    
    try:
        response = client.create_policy(
            policyEngineIdentifier=engine_id,
            name="PatientReadOnlyAccess",
            description="Allow patients to read their own healthcare data",
            policyStatement=policy_statement
        )
        
        policy_id = response['policyId']
        print(f"✅ Policy created: {policy_id}")
        
        return policy_id
        
    except ClientError as e:
        print(f"❌ Error creating policy: {e}")
        raise


def create_patient_appointment_policy(client, engine_id, gateway_arn):
    """Create Cedar policy for patient appointment booking"""
    
    policy_statement = f'''
permit(
  principal,
  action in [
    AgentCore::Action::"Target1___searchSlot",
    AgentCore::Action::"Target1___createAppointment"
  ],
  resource == AgentCore::Gateway::"{gateway_arn}"
) when {{
  principal.hasTag("role") &&
  principal.getTag("role") == "patient" &&
  context.input has patientId &&
  principal.hasTag("sub") &&
  context.input.patientId == principal.getTag("sub")
}};
'''
    
    print("\n📝 Creating patient appointment booking policy...")
    print("Policy allows patients to:")
    print("   • Search for available appointment slots")
    print("   • Create appointments for themselves")
    print("   • Only when patientId matches their authenticated identity (sub)")
    
    try:
        response = client.create_policy(
            policyEngineIdentifier=engine_id,
            name="PatientAppointmentAccess",
            description="Allow patients to search slots and book appointments for themselves",
            policyStatement=policy_statement
        )
        
        policy_id = response['policyId']
        print(f"✅ Policy created: {policy_id}")
        
        return policy_id
        
    except ClientError as e:
        print(f"❌ Error creating policy: {e}")
        raise


def create_healthcare_provider_policy(client, engine_id, gateway_arn):
    """Create Cedar policy for healthcare provider full access"""
    
    policy_statement = f'''
permit(
  principal,
  action,
  resource == AgentCore::Gateway::"{gateway_arn}"
) when {{
  principal.hasTag("role") &&
  principal.getTag("role") in ["doctor", "nurse", "admin"]
}};
'''
    
    print("\n📝 Creating healthcare provider full access policy...")
    print("Policy allows healthcare providers (doctor, nurse, admin) to:")
    print("   • Access all tools without restrictions")
    print("   • View and manage any patient's data")
    
    try:
        response = client.create_policy(
            policyEngineIdentifier=engine_id,
            name="HealthcareProviderFullAccess",
            description="Allow healthcare providers full access to all tools",
            policyStatement=policy_statement
        )
        
        policy_id = response['policyId']
        print(f"✅ Policy created: {policy_id}")
        
        return policy_id
        
    except ClientError as e:
        print(f"❌ Error creating policy: {e}")
        raise


def save_policy_config(config, engine_id, engine_arn, policy_ids):
    """Save policy configuration to policy_config.json"""
    policy_config_file = Path(__file__).parent / "policy_config.json"
    
    policy_config = {
        "region": config.get("region", "us-east-1"),
        "gateway_id": config.get("gateway_id"),
        "gateway_arn": config.get("gateway_arn"),
        "policy_engine": {
            "engine_id": engine_id,
            "engine_arn": engine_arn,
            "mode": "ENFORCE"
        },
        "policies": policy_ids
    }
    
    with open(policy_config_file, "w", encoding="utf-8") as f:
        json.dump(policy_config, f, indent=2)
    
    print(f"\n📝 Policy configuration saved to: {policy_config_file}")


def setup_policy(gateway_id):
    """Main setup function"""
    print("=" * 70)
    print("🚀 Setting up AgentCore Policy for Healthcare Appointment Agent")
    print("=" * 70)
    
    # Load configuration
    print("\n📦 Loading configuration...")
    config = load_config()
    
    region = config.get("region", "us-east-1")
    gateway_arn = config.get("gateway_arn")
    
    if not gateway_arn:
        print("❌ Error: gateway_arn not found in .env file")
        sys.exit(1)
    
    print(f"✅ Configuration loaded")
    print(f"   Region: {region}")
    print(f"   Gateway ID: {gateway_id}")
    print(f"   Gateway ARN: {gateway_arn}")
    
    # Initialize AgentCore client
    print("\n🔧 Initializing AgentCore client...")
    client = boto3.client('bedrock-agentcore', region_name=region)
    print("✅ Client initialized")
    
    # Create Policy Engine
    engine_id, engine_arn = create_policy_engine(client, gateway_arn)
    
    # Attach Policy Engine to Gateway
    attach_policy_engine_to_gateway(client, gateway_id, engine_id)
    
    # Create policies
    policy_ids = {}
    
    policy_ids['patient_read'] = create_patient_read_policy(
        client, engine_id, gateway_arn
    )
    
    policy_ids['patient_appointment'] = create_patient_appointment_policy(
        client, engine_id, gateway_arn
    )
    
    policy_ids['provider_full_access'] = create_healthcare_provider_policy(
        client, engine_id, gateway_arn
    )
    
    # Save configuration
    save_policy_config(config, engine_id, engine_arn, policy_ids)
    
    print("\n" + "=" * 70)
    print("✅ POLICY SETUP COMPLETE!")
    print("=" * 70)
    print(f"Policy Engine ID: {engine_id}")
    print(f"Policy Engine Mode: ENFORCE")
    print(f"\nPolicies Created: {len(policy_ids)}")
    print("   • PatientReadOnlyAccess - Patients can view their own data")
    print("   • PatientAppointmentAccess - Patients can book appointments")
    print("   • HealthcareProviderFullAccess - Providers have full access")
    print("\n🔒 Access control is now enforced on the gateway!")
    print("=" * 70)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Setup AgentCore Policy for Healthcare Appointment Agent'
    )
    parser.add_argument(
        '--gateway_id',
        required=True,
        help='Gateway ID from setup_fhir_mcp.py'
    )
    
    args = parser.parse_args()
    setup_policy(args.gateway_id)
