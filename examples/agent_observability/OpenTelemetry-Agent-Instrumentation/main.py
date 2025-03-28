"""
Example usage of Bedrock Agent Langfuse integration with streaming support.
"""
import time
import boto3
import uuid
import json
from core.timer_lib import timer
from core import instrument_agent_invocation, flush_telemetry

@instrument_agent_invocation
def invoke_bedrock_agent(
    inputText: str, agentId: str, agentAliasId: str, sessionId: str, **kwargs
):
    """Invoke a Bedrock Agent with instrumentation for Langfuse."""
    # Create Bedrock client
    bedrock_rt_client = boto3.client("bedrock-agent-runtime")
    use_streaming = kwargs.get("streaming", False)
    is_inline_agent = kwargs.get("is_inline_agent", False)
    
    # Base parameters for both agent types
    invoke_params = {
        "inputText": inputText,
        "agentId": agentId,
        "agentAliasId": agentAliasId,
        "sessionId": sessionId,
        "enableTrace": True,  # Required for instrumentation
    }

    # Add inline agent specific parameters if needed
    if is_inline_agent:
        invoke_params.update({
            "agentVersion": kwargs.get("agentVersion", "DRAFT"),
            "actionGroupExecutor": kwargs.get("actionGroupExecutor", {}),
            "apiSchema": kwargs.get("apiSchema", {}),
            "knowledgeBaseConfiguration": kwargs.get("knowledgeBaseConfiguration", {}),
            "promptOverrideConfiguration": kwargs.get("promptOverrideConfiguration", {}),
            "sessionAttributes": kwargs.get("sessionAttributes", {}),
            "sessionState": kwargs.get("sessionState", {}),
        })
        # Use invoke_agent_with_response_stream for inline agents
        response = bedrock_rt_client.invoke_agent_with_response_stream(**invoke_params)
    else:
        # Regular agent invocation
        if use_streaming:
            invoke_params["streamingConfigurations"] = {
                "applyGuardrailInterval": 10,
                "streamFinalResponse": use_streaming,
            }
        response = bedrock_rt_client.invoke_agent(**invoke_params)
    
    return response

def process_streaming_response(stream):
    """Process a streaming response from Bedrock Agent."""
    full_response = ""
    try:
        for event in stream:
            # Convert event to dictionary if it's a botocore Event object
            event_dict = (
                event.to_response_dict()
                if hasattr(event, "to_response_dict")
                else event
            )
            if "chunk" in event_dict:
                chunk_data = event_dict["chunk"]
                if "bytes" in chunk_data:
                    output_bytes = chunk_data["bytes"]
                    # Convert bytes to string if needed
                    if isinstance(output_bytes, bytes):
                        output_text = output_bytes.decode("utf-8")
                    else:
                        output_text = str(output_bytes)
                    full_response += output_text
    except Exception as e:
        print(f"\nError processing stream: {e}")
    return full_response

if __name__ == "__main__":
    import os
    import base64
    start = time.time()
    with open('config.json', 'r') as config_file:
        config = json.load(config_file)
    
    # For Langfuse specifically but you can add any other observability provider:
    if "langfuse" in config:
        os.environ["OTEL_SERVICE_NAME"] = 'Langfuse'
        os.environ["DEPLOYMENT_ENVIRONMENT"] = config["langfuse"]["environment"]
        project_name = config["langfuse"]["project_name"]
        environment = config["langfuse"]["environment"]
        langfuse_public_key = config["langfuse"]["langfuse_public_key"]
        langfuse_secret_key = config["langfuse"]["langfuse_secret_key"]
        langfuse_api_url = config["langfuse"]["langfuse_api_url"]
        
        # Create auth header
        auth_token = base64.b64encode(
            f"{langfuse_public_key}:{langfuse_secret_key}".encode()
        ).decode()
        
        # Set OpenTelemetry environment variables for Langfuse
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = f"{langfuse_api_url}/api/public/otel/v1/traces"
        os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = f"Authorization=Basic {auth_token}"

    # Agent configuration
    agentId = config["agent"]["agentId"]
    agentAliasId = config["agent"]["agentAliasId"]
    is_inline_agent = config["agent"].get("is_inline_agent", False)
    sessionId = f"session-{int(time.time())}"

    # User information
    userId = config["user"]["userId"]  
    agent_model_id = config["user"]["agent_model_id"]
    
    # Tags for filtering in Langfuse
    tags = ["bedrock-agent", "example", "development"]
    if is_inline_agent:
        tags.append("inline-agent")
    
    # Generate a custom trace ID
    trace_id = str(uuid.uuid4())
    
    # Prompt
    question = config["question"]["question"]
    streaming = False

    # Prepare agent parameters
    agent_params = {
        "inputText": question,
        "agentId": agentId,
        "agentAliasId": agentAliasId,
        "sessionId": sessionId,
        "show_traces": True,
        "SAVE_TRACE_LOGS": True,
        "userId": userId,
        "tags": tags,
        "trace_id": trace_id,
        "project_name": project_name,
        "environment": environment,
        "langfuse_public_key": langfuse_public_key,
        "langfuse_secret_key": langfuse_secret_key,
        "langfuse_api_url": langfuse_api_url,
        "streaming": streaming,
        "model_id": agent_model_id,
        "is_inline_agent": is_inline_agent
    }

    # Add inline agent specific parameters if needed
    if is_inline_agent:
        agent_params.update({
            "agentVersion": config["agent"].get("agentVersion", "DRAFT"),
            "actionGroupExecutor": config["agent"].get("actionGroupExecutor", {}),
            "apiSchema": config["agent"].get("apiSchema", {}),
            "knowledgeBaseConfiguration": config["agent"].get("knowledgeBaseConfiguration", {}),
            "promptOverrideConfiguration": config["agent"].get("promptOverrideConfiguration", {}),
            "sessionAttributes": config["agent"].get("sessionAttributes", {}),
            "sessionState": config["agent"].get("sessionState", {})
        })

    # Single invocation that works for both streaming and non-streaming
    response = invoke_bedrock_agent(**agent_params)

    # Handle the response appropriately based on streaming mode and agent type
    if isinstance(response, dict) and "error" in response:
        print(f"\nError: {response['error']}")
    elif streaming and isinstance(response, dict) and "completion" in response:
        print("\n🤖 Agent response (streaming):")
        if "extracted_completion" in response:
            print(response["extracted_completion"])
        else:
            process_streaming_response(response["completion"])
    else:
        # Non-streaming response
        print("\n🤖 Agent response:")
        if isinstance(response, dict) and "extracted_completion" in response:
            print(response["extracted_completion"])
        elif (
            isinstance(response, dict) 
            and "completion" in response
            and hasattr(response["completion"], "__iter__")
        ):
            print("Processing completion:")
            full_response = process_streaming_response(response["completion"])
            print(f"\nFull response: {full_response}")
        else:
            print("Raw response:")
            print(f"{response}")

    # Flush telemetry data
    flush_telemetry()
    timer.reset_all()