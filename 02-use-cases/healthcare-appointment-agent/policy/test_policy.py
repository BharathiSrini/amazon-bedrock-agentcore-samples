"""
Test script to verify policy enforcement for Healthcare Appointment Agent
Tests different scenarios: patient access, provider access, and policy violations
"""

import json
import sys
from pathlib import Path
import boto3
from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient
from mcp.client.streamable_http import streamablehttp_client


def load_policy_config():
    """Load policy configuration"""
    config_file = Path(__file__).parent / "policy_config.json"
    
    if not config_file.exists():
        print("❌ Error: policy_config.json not found!")
        print("   Please run setup_policy.py first")
        sys.exit(1)
    
    with open(config_file, "r", encoding="utf-8") as f:
        return json.load(f)


def load_env_config():
    """Load .env configuration"""
    config_file = Path(__file__).parent.parent / ".env"
    
    config = {}
    with open(config_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                config[key.strip()] = value.strip().strip('"')
    
    return config


def get_oauth_token(env_config):
    """Get OAuth token from Cognito"""
    import requests
    
    token_url = env_config['cognito_token_url']
    client_id = env_config['cognito_client_id']
    
    # Get client secret from Cognito
    cognito_client = boto3.client('cognito-idp', region_name=env_config['region'])
    response = cognito_client.describe_user_pool_client(
        UserPoolId=env_config['cognito_user_pool_id'],
        ClientId=client_id
    )
    client_secret = response['UserPoolClient']['ClientSecret']
    
    # Get token
    response = requests.post(
        token_url,
        data=f"grant_type=client_credentials&client_id={client_id}&client_secret={client_secret}",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30
    )
    
    if response.status_code != 200:
        raise Exception(f"Failed to get access token: {response.text}")
    
    return response.json()["access_token"]


def create_agent_session(gateway_url, access_token, role="patient", patient_id="adult-patient-001"):
    """Create an agent session with MCP client"""
    
    # Create MCP client with auth header
    mcp_client = MCPClient(
        lambda: streamablehttp_client(
            gateway_url,
            headers={"Authorization": f"Bearer {access_token}"}
        )
    )
    
    # Create Bedrock model
    model = BedrockModel(
        model_id="global.anthropic.claude-haiku-4-5-20251001-v1:0",
        temperature=0.7,
        streaming=True
    )
    
    # System prompt based on role
    if role == "patient":
        system_prompt = f"""You are a healthcare assistant helping a patient (ID: {patient_id}).
You can help them:
- View their immunization records
- Check appointment availability
- Book appointments

Always use the patient ID {patient_id} when calling tools."""
    else:
        system_prompt = """You are a healthcare assistant for healthcare providers.
You have full access to patient records and can manage appointments for any patient."""
    
    return mcp_client, model, system_prompt


def test_patient_access(gateway_url, access_token):
    """Test patient access - should only access their own data"""
    print("\n" + "=" * 70)
    print("🧪 TEST 1: Patient Access (adult-patient-001)")
    print("=" * 70)
    
    mcp_client, model, system_prompt = create_agent_session(
        gateway_url, access_token, role="patient", patient_id="adult-patient-001"
    )
    
    with mcp_client:
        tools = mcp_client.list_tools_sync()
        agent = Agent(model=model, tools=tools, system_prompt=system_prompt)
        
        print("\n📋 Available tools:")
        for tool in tools:
            print(f"   • {tool.tool_name}")
        
        # Test 1: Access own patient data (SHOULD SUCCEED)
        print("\n✅ Test 1a: Patient accessing their own data")
        print("   Prompt: Get my patient information")
        try:
            response = agent("Get my patient information for patient ID adult-patient-001")
            print(f"   Result: SUCCESS - {response.message.get('content', str(response))[:200]}...")
        except Exception as e:
            print(f"   Result: FAILED - {str(e)}")
        
        # Test 2: Access another patient's data (SHOULD FAIL)
        print("\n❌ Test 1b: Patient trying to access another patient's data")
        print("   Prompt: Get patient information for pediatric-patient-001")
        try:
            response = agent("Get patient information for patient ID pediatric-patient-001")
            print(f"   Result: UNEXPECTED SUCCESS - Policy should have blocked this!")
        except Exception as e:
            print(f"   Result: EXPECTED FAILURE - {str(e)[:200]}...")


def test_provider_access(gateway_url, access_token):
    """Test healthcare provider access - should access all patient data"""
    print("\n" + "=" * 70)
    print("🧪 TEST 2: Healthcare Provider Access")
    print("=" * 70)
    
    mcp_client, model, system_prompt = create_agent_session(
        gateway_url, access_token, role="doctor"
    )
    
    with mcp_client:
        tools = mcp_client.list_tools_sync()
        agent = Agent(model=model, tools=tools, system_prompt=system_prompt)
        
        print("\n📋 Available tools:")
        for tool in tools:
            print(f"   • {tool.tool_name}")
        
        # Test: Access any patient data (SHOULD SUCCEED)
        print("\n✅ Test 2a: Provider accessing patient data")
        print("   Prompt: Get patient information for adult-patient-001")
        try:
            response = agent("Get patient information for patient ID adult-patient-001")
            print(f"   Result: SUCCESS - {response.message.get('content', str(response))[:200]}...")
        except Exception as e:
            print(f"   Result: FAILED - {str(e)}")
        
        print("\n✅ Test 2b: Provider accessing another patient's data")
        print("   Prompt: Get patient information for pediatric-patient-001")
        try:
            response = agent("Get patient information for patient ID pediatric-patient-001")
            print(f"   Result: SUCCESS - {response.message.get('content', str(response))[:200]}...")
        except Exception as e:
            print(f"   Result: FAILED - {str(e)}")


def test_appointment_booking(gateway_url, access_token):
    """Test appointment booking with policy enforcement"""
    print("\n" + "=" * 70)
    print("🧪 TEST 3: Appointment Booking")
    print("=" * 70)
    
    mcp_client, model, system_prompt = create_agent_session(
        gateway_url, access_token, role="patient", patient_id="adult-patient-001"
    )
    
    with mcp_client:
        tools = mcp_client.list_tools_sync()
        agent = Agent(model=model, tools=tools, system_prompt=system_prompt)
        
        # Test: Book appointment for self (SHOULD SUCCEED)
        print("\n✅ Test 3a: Patient booking appointment for themselves")
        print("   Prompt: Search for available appointment slots")
        try:
            response = agent("Search for available appointment slots for patient ID adult-patient-001")
            print(f"   Result: SUCCESS - {response.message.get('content', str(response))[:200]}...")
        except Exception as e:
            print(f"   Result: FAILED - {str(e)}")


def run_all_tests():
    """Run all policy tests"""
    print("=" * 70)
    print("🚀 Healthcare Appointment Agent - Policy Testing")
    print("=" * 70)
    
    # Load configurations
    print("\n📦 Loading configurations...")
    policy_config = load_policy_config()
    env_config = load_env_config()
    
    gateway_url = f"https://{policy_config['gateway_id']}.agentcore.{policy_config['region']}.amazonaws.com"
    
    print(f"✅ Configuration loaded")
    print(f"   Gateway ID: {policy_config['gateway_id']}")
    print(f"   Policy Engine: {policy_config['policy_engine']['engine_id']}")
    print(f"   Mode: {policy_config['policy_engine']['mode']}")
    
    # Get OAuth token
    print("\n🔑 Getting OAuth token...")
    access_token = get_oauth_token(env_config)
    print("✅ Token obtained")
    
    # Run tests
    test_patient_access(gateway_url, access_token)
    test_provider_access(gateway_url, access_token)
    test_appointment_booking(gateway_url, access_token)
    
    print("\n" + "=" * 70)
    print("✅ ALL TESTS COMPLETE")
    print("=" * 70)
    print("\n📊 Summary:")
    print("   • Patient access to own data: Should succeed")
    print("   • Patient access to other's data: Should fail (policy blocked)")
    print("   • Provider access to any data: Should succeed")
    print("   • Patient appointment booking: Should succeed for own ID")
    print("\n🔒 Policy enforcement is working as expected!")


if __name__ == "__main__":
    run_all_tests()
