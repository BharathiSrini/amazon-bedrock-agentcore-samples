"""
Cleanup script to remove Policy Engine and policies from Healthcare Gateway
"""

import json
import sys
from pathlib import Path
import boto3
from botocore.exceptions import ClientError


def load_policy_config():
    """Load policy configuration"""
    config_file = Path(__file__).parent / "policy_config.json"
    
    if not config_file.exists():
        print("⚠️  No policy_config.json found - nothing to clean up")
        sys.exit(0)
    
    with open(config_file, "r", encoding="utf-8") as f:
        return json.load(f)


def detach_policy_engine(client, gateway_id):
    """Detach policy engine from gateway"""
    print(f"\n📝 Detaching Policy Engine from Gateway...")
    
    try:
        client.update_gateway(
            gatewayIdentifier=gateway_id,
            policyEngineId=None
        )
        print("✅ Policy Engine detached from Gateway")
    except ClientError as e:
        print(f"⚠️  Error detaching Policy Engine: {e}")


def delete_policies(client, engine_id, policy_ids):
    """Delete all policies from the engine"""
    print(f"\n📝 Deleting policies...")
    
    for policy_name, policy_id in policy_ids.items():
        try:
            client.delete_policy(
                policyEngineIdentifier=engine_id,
                policyId=policy_id
            )
            print(f"✅ Deleted policy: {policy_name}")
        except ClientError as e:
            print(f"⚠️  Error deleting policy {policy_name}: {e}")


def delete_policy_engine(client, engine_id):
    """Delete the policy engine"""
    print(f"\n📝 Deleting Policy Engine...")
    
    try:
        client.delete_policy_engine(
            policyEngineIdentifier=engine_id
        )
        print("✅ Policy Engine deleted")
    except ClientError as e:
        print(f"⚠️  Error deleting Policy Engine: {e}")


def cleanup_policy(gateway_id):
    """Main cleanup function"""
    print("=" * 70)
    print("🧹 Cleaning up AgentCore Policy for Healthcare Appointment Agent")
    print("=" * 70)
    
    # Load configuration
    print("\n📦 Loading policy configuration...")
    config = load_policy_config()
    
    region = config.get("region", "us-east-1")
    engine_id = config["policy_engine"]["engine_id"]
    policy_ids = config.get("policies", {})
    
    print(f"✅ Configuration loaded")
    print(f"   Region: {region}")
    print(f"   Gateway ID: {gateway_id}")
    print(f"   Policy Engine ID: {engine_id}")
    print(f"   Policies to delete: {len(policy_ids)}")
    
    # Initialize AgentCore client
    print("\n🔧 Initializing AgentCore client...")
    client = boto3.client('bedrock-agentcore', region_name=region)
    print("✅ Client initialized")
    
    # Detach policy engine from gateway
    detach_policy_engine(client, gateway_id)
    
    # Delete policies
    if policy_ids:
        delete_policies(client, engine_id, policy_ids)
    
    # Delete policy engine
    delete_policy_engine(client, engine_id)
    
    # Remove policy config file
    config_file = Path(__file__).parent / "policy_config.json"
    try:
        config_file.unlink()
        print(f"\n📝 Removed policy_config.json")
    except Exception as e:
        print(f"⚠️  Could not remove policy_config.json: {e}")
    
    print("\n" + "=" * 70)
    print("✅ POLICY CLEANUP COMPLETE!")
    print("=" * 70)
    print("🔓 Access control has been removed from the gateway")
    print("   The gateway will now allow all authenticated requests")
    print("=" * 70)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Cleanup AgentCore Policy for Healthcare Appointment Agent'
    )
    parser.add_argument(
        '--gateway_id',
        required=True,
        help='Gateway ID'
    )
    
    args = parser.parse_args()
    cleanup_policy(args.gateway_id)
