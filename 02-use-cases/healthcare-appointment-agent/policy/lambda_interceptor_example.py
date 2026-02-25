"""
Lambda Interceptor Example for Healthcare Agent Policy

This Lambda function enriches the request context with derived data needed
for advanced Cedar policy evaluation, including:
- Parent-child relationships
- Appointment counts and abuse detection
- Time-based flags
- Geographic information

Deploy this as a Lambda function and configure it as an interceptor
in your AgentCore Gateway configuration.
"""

import json
import boto3
from datetime import datetime, timedelta
from typing import Dict, List, Any

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
healthlake = boto3.client('healthlake')

# Configuration
PATIENT_RELATIONSHIPS_TABLE = 'patient-relationships'
APPOINTMENT_HISTORY_TABLE = 'appointment-history'
RATE_LIMIT_TABLE = 'rate-limits'


def lambda_handler(event, context):
    """
    Lambda interceptor handler for AgentCore Gateway
    
    Input event structure:
    {
        "principal": {
            "sub": "adult-patient-001",
            "role": "patient"
        },
        "action": "Target1___createAppointment",
        "resource": "arn:aws:bedrock-agentcore:...",
        "context": {
            "input": {
                "patientId": "pediatric-patient-001",
                "facilityId": "facility-123",
                "specialty": "pediatrics"
            }
        }
    }
    
    Output: Enriched context with derived data
    """
    
    try:
        # Extract request details
        principal = event.get('principal', {})
        action = event.get('action', '')
        request_context = event.get('context', {})
        input_params = request_context.get('input', {})
        
        # Initialize enriched context
        enriched_context = {
            **request_context,
            'identity': {},
            'derived': {},
            'time': {},
            'geo': {},
            'rateLimit': {},
            'audit': {}
        }
        
        # 1. Enrich identity with parent-child relationships
        enriched_context['identity'] = enrich_identity(principal)
        
        # 2. Add derived appointment data
        if 'patientId' in input_params:
            enriched_context['derived'] = get_derived_appointment_data(
                input_params.get('patientId'),
                input_params.get('specialty'),
                input_params.get('appointmentDate')
            )
        
        # 3. Add time context
        enriched_context['time'] = get_time_context()
        
        # 4. Add geographic context
        enriched_context['geo'] = get_geo_context(event)
        
        # 5. Add rate limiting data
        if principal.get('sub'):
            enriched_context['rateLimit'] = get_rate_limit_data(
                principal['sub'],
                action
            )
        
        # 6. Add audit context
        enriched_context['audit'] = {
            'requestId': context.request_id,
            'timestamp': datetime.utcnow().isoformat(),
            'sourceIp': event.get('requestContext', {}).get('identity', {}).get('sourceIp')
        }
        
        # Return enriched event
        return {
            **event,
            'context': enriched_context
        }
        
    except Exception as e:
        print(f"Error in Lambda interceptor: {str(e)}")
        # Return original event if enrichment fails
        return event


def enrich_identity(principal: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enrich identity with parent-child relationships and other attributes
    
    Returns:
    {
        "sub": "adult-patient-001",
        "children": ["pediatric-patient-001", "pediatric-patient-002"],
        "assignedFacilities": ["facility-123", "facility-456"],
        "assignedPatients": ["patient-001", "patient-002", ...]
    }
    """
    identity = {
        'sub': principal.get('sub'),
        'children': [],
        'assignedFacilities': [],
        'assignedPatients': []
    }
    
    try:
        table = dynamodb.Table(PATIENT_RELATIONSHIPS_TABLE)
        
        # Get parent-child relationships
        if principal.get('role') == 'patient':
            response = table.get_item(
                Key={'userId': principal['sub']}
            )
            
            if 'Item' in response:
                identity['children'] = response['Item'].get('children', [])
        
        # Get staff assignments
        elif principal.get('role') in ['scheduler', 'clinician', 'nurse']:
            response = table.get_item(
                Key={'userId': principal['sub']}
            )
            
            if 'Item' in response:
                identity['assignedFacilities'] = response['Item'].get('assignedFacilities', [])
                identity['assignedPatients'] = response['Item'].get('assignedPatients', [])
        
    except Exception as e:
        print(f"Error enriching identity: {str(e)}")
    
    return identity


def get_derived_appointment_data(
    patient_id: str,
    specialty: str = None,
    appointment_date: str = None
) -> Dict[str, Any]:
    """
    Calculate derived appointment data for policy evaluation
    
    Returns:
    {
        "upcomingAppointmentsInSpecialty": 2,
        "totalUpcomingAppointments": 5,
        "isSameDay": false,
        "isSurgeryOrProcedure": false,
        "recentCancellations": 1,
        "noShowCount": 0
    }
    """
    derived = {
        'upcomingAppointmentsInSpecialty': 0,
        'totalUpcomingAppointments': 0,
        'isSameDay': False,
        'isSurgeryOrProcedure': False,
        'recentCancellations': 0,
        'noShowCount': 0
    }
    
    try:
        table = dynamodb.Table(APPOINTMENT_HISTORY_TABLE)
        
        # Query upcoming appointments
        now = datetime.utcnow()
        response = table.query(
            KeyConditionExpression='patientId = :pid AND appointmentDate >= :now',
            ExpressionAttributeValues={
                ':pid': patient_id,
                ':now': now.isoformat()
            }
        )
        
        appointments = response.get('Items', [])
        derived['totalUpcomingAppointments'] = len(appointments)
        
        # Count appointments in specific specialty
        if specialty:
            specialty_appointments = [
                apt for apt in appointments
                if apt.get('specialty') == specialty
            ]
            derived['upcomingAppointmentsInSpecialty'] = len(specialty_appointments)
        
        # Check if appointment is same-day
        if appointment_date:
            apt_date = datetime.fromisoformat(appointment_date)
            derived['isSameDay'] = apt_date.date() == now.date()
        
        # Check if appointment is surgery/procedure
        # (This would check against a list of procedure codes)
        surgery_specialties = ['surgery', 'orthopedics', 'cardiology']
        if specialty and specialty.lower() in surgery_specialties:
            derived['isSurgeryOrProcedure'] = True
        
        # Count recent cancellations (last 30 days)
        thirty_days_ago = now - timedelta(days=30)
        response = table.query(
            KeyConditionExpression='patientId = :pid AND appointmentDate >= :start',
            FilterExpression='appointmentStatus = :cancelled',
            ExpressionAttributeValues={
                ':pid': patient_id,
                ':start': thirty_days_ago.isoformat(),
                ':cancelled': 'cancelled'
            }
        )
        derived['recentCancellations'] = len(response.get('Items', []))
        
        # Count no-shows (last 90 days)
        ninety_days_ago = now - timedelta(days=90)
        response = table.query(
            KeyConditionExpression='patientId = :pid AND appointmentDate >= :start',
            FilterExpression='appointmentStatus = :noshow',
            ExpressionAttributeValues={
                ':pid': patient_id,
                ':start': ninety_days_ago.isoformat(),
                ':noshow': 'no-show'
            }
        )
        derived['noShowCount'] = len(response.get('Items', []))
        
    except Exception as e:
        print(f"Error getting derived appointment data: {str(e)}")
    
    return derived


def get_time_context() -> Dict[str, Any]:
    """
    Get current time context for time-based policies
    
    Returns:
    {
        "hour": 14,
        "minute": 30,
        "dayOfWeek": "Monday",
        "isWeekend": false,
        "isHoliday": false
    }
    """
    now = datetime.utcnow()
    
    return {
        'hour': now.hour,
        'minute': now.minute,
        'dayOfWeek': now.strftime('%A'),
        'isWeekend': now.weekday() >= 5,
        'isHoliday': check_if_holiday(now),
        'timestamp': now.isoformat()
    }


def check_if_holiday(date: datetime) -> bool:
    """
    Check if date is a holiday
    (Simplified - in production, use a holiday calendar service)
    """
    # US Federal Holidays (simplified)
    holidays = [
        (1, 1),   # New Year's Day
        (7, 4),   # Independence Day
        (12, 25), # Christmas
    ]
    
    return (date.month, date.day) in holidays


def get_geo_context(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get geographic context from request
    
    Returns:
    {
        "region": "US-EAST",
        "country": "US",
        "sourceIp": "192.168.1.1"
    }
    """
    # In production, use IP geolocation service
    # For now, return default region
    
    source_ip = event.get('requestContext', {}).get('identity', {}).get('sourceIp')
    
    # Simplified region detection
    # In production, use MaxMind GeoIP or similar
    region = determine_region_from_ip(source_ip)
    
    return {
        'region': region,
        'country': 'US',
        'sourceIp': source_ip
    }


def determine_region_from_ip(ip: str) -> str:
    """
    Determine region from IP address
    (Simplified - in production, use GeoIP service)
    """
    # Default to US-EAST for this example
    return 'US-EAST'


def get_rate_limit_data(user_id: str, action: str) -> Dict[str, Any]:
    """
    Get rate limiting data for abuse prevention
    
    Returns:
    {
        "appointmentsCreatedInLastHour": 2,
        "appointmentsCreatedToday": 5,
        "cancellationsInLastWeek": 1,
        "isRateLimited": false
    }
    """
    rate_limit = {
        'appointmentsCreatedInLastHour': 0,
        'appointmentsCreatedToday': 0,
        'cancellationsInLastWeek': 0,
        'isRateLimited': False
    }
    
    try:
        table = dynamodb.Table(RATE_LIMIT_TABLE)
        now = datetime.utcnow()
        
        # Get rate limit data
        response = table.get_item(
            Key={'userId': user_id}
        )
        
        if 'Item' in response:
            item = response['Item']
            
            # Count actions in last hour
            one_hour_ago = now - timedelta(hours=1)
            recent_actions = [
                a for a in item.get('recentActions', [])
                if datetime.fromisoformat(a['timestamp']) > one_hour_ago
                and a['action'] == 'createAppointment'
            ]
            rate_limit['appointmentsCreatedInLastHour'] = len(recent_actions)
            
            # Count actions today
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            today_actions = [
                a for a in item.get('recentActions', [])
                if datetime.fromisoformat(a['timestamp']) > today_start
                and a['action'] == 'createAppointment'
            ]
            rate_limit['appointmentsCreatedToday'] = len(today_actions)
            
            # Count cancellations in last week
            one_week_ago = now - timedelta(days=7)
            recent_cancellations = [
                a for a in item.get('recentActions', [])
                if datetime.fromisoformat(a['timestamp']) > one_week_ago
                and a['action'] == 'cancelAppointment'
            ]
            rate_limit['cancellationsInLastWeek'] = len(recent_cancellations)
            
            # Check if rate limited
            rate_limit['isRateLimited'] = (
                rate_limit['appointmentsCreatedInLastHour'] >= 5 or
                rate_limit['cancellationsInLastWeek'] >= 10
            )
        
        # Update rate limit table with current action
        update_rate_limit_table(user_id, action, now)
        
    except Exception as e:
        print(f"Error getting rate limit data: {str(e)}")
    
    return rate_limit


def update_rate_limit_table(user_id: str, action: str, timestamp: datetime):
    """
    Update rate limit table with current action
    """
    try:
        table = dynamodb.Table(RATE_LIMIT_TABLE)
        
        # Add current action to recent actions
        table.update_item(
            Key={'userId': user_id},
            UpdateExpression='SET recentActions = list_append(if_not_exists(recentActions, :empty_list), :action)',
            ExpressionAttributeValues={
                ':empty_list': [],
                ':action': [{
                    'action': action,
                    'timestamp': timestamp.isoformat()
                }]
            }
        )
        
    except Exception as e:
        print(f"Error updating rate limit table: {str(e)}")


# ============================================================================
# DynamoDB Table Schemas
# ============================================================================

"""
Table: patient-relationships
Schema:
{
    "userId": "adult-patient-001",  # Partition key
    "userType": "patient",
    "children": ["pediatric-patient-001", "pediatric-patient-002"],
    "assignedFacilities": [],  # For staff
    "assignedPatients": []     # For staff
}

Table: appointment-history
Schema:
{
    "patientId": "adult-patient-001",  # Partition key
    "appointmentDate": "2024-03-15T10:00:00Z",  # Sort key
    "appointmentId": "apt-123",
    "specialty": "pediatrics",
    "facilityId": "facility-123",
    "appointmentStatus": "scheduled|cancelled|no-show|completed",
    "appointmentType": "routine|surgery|procedure"
}

Table: rate-limits
Schema:
{
    "userId": "adult-patient-001",  # Partition key
    "recentActions": [
        {
            "action": "createAppointment",
            "timestamp": "2024-03-15T10:00:00Z"
        }
    ],
    "ttl": 1234567890  # Auto-expire old records
}
"""
