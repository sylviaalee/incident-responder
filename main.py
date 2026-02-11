"""
Incident Response Pipeline using CrewAI
A multi-agent system that triages incidents, diagnoses root causes, and drafts remediation plans.
"""

from crewai import Agent, Task, Crew, Process
from crewai.tools import tool
import json
from typing import Dict, List, Any
from datetime import datetime


# =====================
# TOOL DEFINITIONS
# =====================

@tool("Query Metrics")
def query_metrics(service_name: str) -> str:
    """
    Query Prometheus-style metrics for a specific service.
    Returns error rate, latency, and throughput data as JSON with some junk data.
    
    Args:
        service_name: Name of the service to query (e.g., 'payment-service')
    """
    try:
        with open('metrics.json', 'r') as f:
            content = f.read()
        return content
    except FileNotFoundError:
        return json.dumps({"error": "metrics.json not found", "service": service_name})


@tool("Search Logs")
def search_logs(keyword: str) -> str:
    """
    Search application logs for a keyword or pattern.
    Returns matching log lines from logs.txt (200 lines, includes junk).
    
    Args:
        keyword: Keyword to search for in logs (e.g., 'error', 'timeout')
    """
    try:
        with open('logs.txt', 'r') as f:
            lines = f.readlines()
        
        matching = [line for line in lines if keyword.lower() in line.lower()]
        
        if not matching:
            return f"No logs found matching '{keyword}'"
        
        # Return up to 50 matching lines
        result = f"Found {len(matching)} matching log entries:\n\n"
        result += ''.join(matching[:50])
        
        if len(matching) > 50:
            result += f"\n... ({len(matching) - 50} more matches not shown)"
        
        return result
    except FileNotFoundError:
        return "logs.txt not found"


@tool("Get Recent Deploys")
def get_recent_deploys(service_name: str = None) -> str:
    """
    Get recent deployment history.
    Reads from deploys.log mock file.
    
    Args:
        service_name: Optional service name to filter by
    """
    try:
        with open('deploys.log', 'r') as f:
            content = f.read()
        return content
    except FileNotFoundError:
        return "deploys.log not found"


@tool("Search Runbooks")
def search_runbooks(keyword: str) -> str:
    """
    Search runbook directory for procedures matching a keyword.
    Returns markdown content from matching runbook files.
    
    Args:
        keyword: Keyword to search for (e.g., 'database', 'rollback', 'cache')
    """
    import os
    import glob
    
    runbook_dir = 'runbooks'
    
    if not os.path.exists(runbook_dir):
        return json.dumps({
            "error": "runbooks directory not found",
            "confidence": "low",
            "recommendation": "No matching runbook - create custom remediation plan"
        })
    
    # Search for markdown files containing the keyword
    matches = []
    for filepath in glob.glob(os.path.join(runbook_dir, '*.md')):
        filename = os.path.basename(filepath)
        if keyword.lower() in filename.lower():
            try:
                with open(filepath, 'r') as f:
                    content = f.read()
                matches.append({
                    "runbook": filename,
                    "content": content
                })
            except Exception as e:
                continue
    
    if not matches:
        return json.dumps({
            "error": f"No runbooks found matching '{keyword}'",
            "confidence": "low",
            "recommendation": "No matching runbook - create custom remediation plan based on diagnosis"
        })
    
    # Return first match
    result = f"Found {len(matches)} matching runbook(s):\n\n"
    result += f"=== {matches[0]['runbook']} ===\n\n"
    result += matches[0]['content']
    
    return result


# =====================
# AGENT DEFINITIONS
# =====================

# Agent 1: Triage Specialist
triage_agent = Agent(
    role='Incident Triage Specialist',
    goal='Assess incident severity, identify affected services, and determine priority level',
    backstory="""You are a veteran SRE with 15 years of experience in production incident response.
    You've seen thousands of incidents and have developed an intuition for quickly separating 
    critical issues from noise. You excel at reading between the lines of incident reports,
    asking the right questions, and determining blast radius. Your assessments are concise,
    data-driven, and actionable. You never panic, but you know when to escalate.""",
    verbose=True,
    allow_delegation=False,
    tools=[query_metrics, search_logs]
)

# Agent 2: Diagnostics Engineer
diagnostic_agent = Agent(
    role='Root Cause Analysis Engineer',
    goal='Systematically diagnose incidents by analyzing all available signals, identifying recent changes, and ranking hypotheses by likelihood',
    backstory="""You are a senior software engineer who specializes in debugging complex distributed systems.
    You approach problems methodically using a structured diagnostic framework:
    
    1. SIGNAL INVENTORY: First, list ALL available data sources (metrics, logs, traces, deployment history)
    2. CHANGE ANALYSIS: Identify what changed recently (deployments, config changes, traffic patterns, dependencies)
    3. HYPOTHESIS FORMATION: Generate multiple hypotheses based on common failure patterns
    4. LIKELIHOOD RANKING: Assign a single likelihood score (0.0-1.0) to each hypothesis based on evidence
    
    You're familiar with common failure patterns: cascading failures, connection pool exhaustion, 
    timeout misconfigurations, memory leaks, deployment issues, resource contention, and external dependencies.
    
    You write clear, technical diagnoses that explain not just what broke, but why and how, with evidence 
    supporting each hypothesis. Your output always includes a ranked list of hypotheses with likelihood scores.""",
    verbose=True,
    allow_delegation=False,
    tools=[search_logs, get_recent_deploys, query_metrics]
)

# Agent 3: Remediation Planner
remediation_agent = Agent(
    role='Remediation Strategy Planner',
    goal='Develop actionable, prioritized remediation plans with immediate mitigation and long-term fixes',
    backstory="""You are a principal engineer and incident commander with expertise in crisis management.
    You translate root cause analyses into clear, executable action plans. You think in terms of
    immediate mitigation (stop the bleeding), short-term fixes (restore service), and long-term
    prevention (ensure it never happens again). You prioritize actions by impact and urgency,
    provide specific commands and configuration changes, and always consider rollback plans.
    
    When no runbook matches, you still produce a best-effort plan and flag confidence as low.
    
    Your remediation plans have saved companies millions in downtime costs.""",
    verbose=True,
    allow_delegation=False,
    tools=[search_runbooks]
)


# =====================
# TASK DEFINITIONS
# =====================

def create_triage_task(incident: Dict[str, Any]) -> Task:
    """Create the triage task"""
    return Task(
        description=f"""Analyze this production incident and provide a triage assessment:
        
        INCIDENT DETAILS:
        {json.dumps(incident, indent=2)}
        
        Your triage should include:
        1. Severity classification (P0-Critical, P1-High, P2-Medium, P3-Low)
        2. List of affected services (primary and secondary)
        3. Estimated blast radius and customer impact
        4. Current metrics for affected services (query using tools)
        5. Dependencies that might be impacted
        6. Recommended escalation level
        7. Initial observations about the incident
        
        Use the query_metrics and search_logs tools to gather data.
        Be concise but thorough. Time is critical.
        
        Return your assessment as structured JSON with the following fields:
        - affected_service
        - started_at
        - severity
        - symptoms (list)
        - metrics_snapshot (error_rate, latency_p99, throughput)""",
        agent=triage_agent,
        expected_output="A structured JSON triage assessment with severity, affected services, blast radius, and metrics snapshot"
    )


def create_diagnostic_task(incident: Dict[str, Any]) -> Task:
    """Create the diagnostic/RCA task"""
    return Task(
        description=f"""Conduct a root cause analysis for this incident:
        
        INCIDENT DETAILS:
        {json.dumps(incident, indent=2)}
        
        Investigate and provide:
        1. Timeline of when issues started (correlate with metrics and deployments)
        2. Detailed examination of metrics trends (error rates, latency, throughput)
        3. Analysis of error logs for patterns and specific failures
        4. Review of recent deployments that might be correlated
        5. Multiple hypotheses about the root cause
        6. Evidence supporting each hypothesis (metrics, logs, timing)
        7. Likelihood ranking (0.0-1.0) for each hypothesis
        8. Explanation of the failure mechanism (why it happened)
        
        Use all available tools: search_logs, get_recent_deploys, and query_metrics.
        Form multiple hypotheses and rank them by likelihood based on evidence.
        
        Return your diagnosis as structured JSON with:
        - hypotheses (list of objects with: description, likelihood, supporting_evidence, contradicting_evidence, change_event)""",
        agent=diagnostic_agent,
        expected_output="A structured JSON diagnosis with ranked hypotheses, each containing likelihood score, supporting evidence, and contradicting evidence",
        context=[create_triage_task(incident)]  # Depends on triage task output
    )


def create_remediation_task(incident: Dict[str, Any]) -> Task:
    """Create the remediation planning task"""
    return Task(
        description=f"""Based on the triage and root cause analysis, create a comprehensive remediation plan:
        
        INCIDENT DETAILS:
        {json.dumps(incident, indent=2)}
        
        Your remediation plan should include:
        
        IMMEDIATE ACTIONS (next 15 minutes):
        - Emergency mitigations to stop customer impact
        - Specific commands, configuration changes, or rollback procedures
        - Who should execute each action
        
        SHORT-TERM FIXES (next 24 hours):
        - Actions to fully restore service
        - Monitoring to confirm fix effectiveness
        - Communication plan for stakeholders
        
        LONG-TERM PREVENTION (next sprint):
        - Architectural or code changes to prevent recurrence
        - Improved monitoring and alerting
        - Runbook updates or new documentation
        - Post-mortem action items
        
        ROLLBACK PLAN:
        - Steps to revert changes if remediation fails
        - Decision criteria for when to rollback
        
        Use search_runbooks tool to reference standard procedures. If no runbook matches,
        still produce a best-effort plan and set confidence to "low".
        
        Make your plan specific, actionable, and prioritized. Include exact commands where possible.
        
        Return as structured JSON with:
        - runbook_match (filename or null)
        - steps (list of action strings)
        - blast_radius
        - rollback_plan
        - confidence (high/medium/low)""",
        agent=remediation_agent,
        expected_output="A structured JSON remediation plan with runbook match, prioritized steps, rollback plan, and confidence level",
        context=[create_triage_task(incident), create_diagnostic_task(incident)]  # Depends on both previous tasks
    )


# =====================
# CREW DEFINITION
# =====================

def run_incident_response(incident: Dict[str, Any]) -> str:
    """
    Execute the incident response pipeline
    
    Args:
        incident: Incident data as a dictionary
        
    Returns:
        Complete incident response output
    """
    # Create tasks
    triage_task = create_triage_task(incident)
    diagnostic_task = create_diagnostic_task(incident)
    remediation_task = create_remediation_task(incident)
    
    # Create crew with sequential process
    crew = Crew(
        agents=[triage_agent, diagnostic_agent, remediation_agent],
        tasks=[triage_task, diagnostic_task, remediation_task],
        process=Process.sequential,  # Tasks execute in order, each can use previous outputs
        verbose=True  # Maximum verbosity to see agent reasoning
    )
    
    # Execute the pipeline
    result = crew.kickoff()
    
    return result


# =====================
# MAIN EXECUTION
# =====================

if __name__ == "__main__":
    # Load test incident from file
    with open('test_incidents.json', 'r') as f:
        incidents = json.load(f)
    
    # Use first incident as example
    sample_incident = incidents[0]
    
    print("=" * 80)
    print("INCIDENT RESPONSE PIPELINE - CREWAI")
    print("=" * 80)
    print(f"\nProcessing incident: {sample_incident['id']}")
    print(f"Title: {sample_incident['title']}\n")
    
    # Run the incident response pipeline
    response = run_incident_response(sample_incident)
    
    print("\n" + "=" * 80)
    print("INCIDENT RESPONSE COMPLETE")
    print("=" * 80)
    print(response)