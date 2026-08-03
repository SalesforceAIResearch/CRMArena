from os import getenv
from typing import List
import logging
import json

import requests
from requests.adapters import HTTPAdapter, Retry
from requests.models import Response

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SuperfaceTool:
    def __init__(self, name: str, description: str, input: dict, is_safe: bool, perform: callable):        
        self.name = name
        self.description = description
        self.is_safe = is_safe
        self.input_schema = json_schema_to_pydantic(input)
        self.input_schema_raw = input
        self.perform = perform

    def run(self, arguments: dict | None = None):
        return self.perform(arguments)

class Superface:
    def __init__(self, api_key: str, base_url: str):
        if (not api_key):
            raise SuperfaceException("Please provide a valid API secret token")
        
        self.api = SuperfaceAPI(api_key=api_key, base_url=base_url)

    def get_tools(self, user_id: str) -> List[SuperfaceTool]:
        try:
            logger.info(f"Getting tools for user {user_id}")
            function_descriptor = self.api.get(user_id=user_id, path='?fd')
            logger.info(f"Received function descriptor: {function_descriptor}")
            
            # Wrap single descriptor in a list if it's not already a list
            function_descriptors = [function_descriptor] if isinstance(function_descriptor, dict) else function_descriptor
            
            if not isinstance(function_descriptors, list):
                logger.error(f"Expected dictionary or list of function descriptors, got {type(function_descriptor)}")
                raise SuperfaceException(f"Invalid response format from API. Expected dictionary or list, got {type(function_descriptor)}")
            
            tools = []
            
            for descriptor in function_descriptors:
                if not isinstance(descriptor, dict):
                    logger.error(f"Expected dictionary for function descriptor, got {type(descriptor)}")
                    continue
                    
                tool_name = descriptor['name']
                logger.info(f"Creating tool: {tool_name}")
                
                def perform(arguments: dict | None, tool_name: str = tool_name):
                    perform_path = f"/"
                    data = arguments if arguments else dict()
                    logger.info(f"Calling {tool_name} with arguments: {data}")
                    result = self.api.post(user_id=user_id, path=perform_path, data=data)
                    logger.info(f"Received result from {tool_name}: {result}")
                    return result

                tool = SuperfaceTool(
                    name=tool_name,
                    description=descriptor['description'],
                    input=descriptor['parameters'],
                    is_safe=False,
                    perform=perform
                )
                
                tools.append(tool)
            
            return tools
        except Exception as e:
            logger.error(f"Error in get_tools: {str(e)}", exc_info=True)
            raise

    def is_tool_connected(self, user_id: str, tool_name: str) -> dict:
        """
        Check if a tool is connected for a user
        
        Args:
            user_id: User ID to check
            tool_name: Name of the tool to check
            
        Returns:
            Object containing provider ID and connection status
            
        Raises:
            SuperfaceException: If the request fails
        """
        response = self.api.get(user_id=user_id, path=f"/tools/{tool_name}")
        
        return {
            "provider": response.get("provider"),
            "connected": response.get("connected", False)
        }

class SuperfaceAPI:
    def __init__(self, *, 
                 api_key: str, 
                 base_url: str = "https://pod.superface.ai/api/specialists/salesforce"):
        self.api_key = api_key
        self.base_url = base_url

    def get(self, *, user_id: str, path: str):
        url = f"{self.base_url}{path}"
        logger.info(f"Making GET request to {url}")

        s = requests.Session()

        retries = Retry(total=3,
                        backoff_factor=0.1,
                        status_forcelist=[ 500, 501, 502, 503, 504 ])

        s.mount('https://', HTTPAdapter(max_retries=retries))
        
        response = s.get(url, headers=self._get_headers(user_id))
        logger.info(f"GET response status: {response.status_code}")
        logger.info(f"GET response headers: {response.headers}")
        logger.info(f"GET response content: {response.text}")

        return self._handle_response(response)

    def post(self, *, user_id: str, path: str, data: dict):
        url = f"{self.base_url}{path}"
        logger.info(f"Making POST request to {url}")
        logger.info(f"POST request data: {data}")
        
        response = requests.post(
            url,
            json=data,
            headers=self._get_headers(user_id)
        )
        logger.info(f"POST response status: {response.status_code}")
        logger.info(f"POST response headers: {response.headers}")
        logger.info(f"POST response content: {response.text}")

        return self._handle_response(response)
    
    def _handle_response(self, response: Response):
        if response.status_code >= 200 and response.status_code < 210:
            try:
                json_response = response.json()
                logger.info(f"Parsed JSON response: {json_response}")
                
                # Handle double-encoded JSON in result field
                if isinstance(json_response.get('result'), str):
                    try:
                        # First, try to parse the result string as JSON
                        parsed_result = json.loads(json_response['result'])
                        # If the parsed result is a string that looks like JSON, parse it again
                        if isinstance(parsed_result, str) and (parsed_result.startswith('{') or parsed_result.startswith('[')):
                            try:
                                parsed_result = json.loads(parsed_result)
                            except json.JSONDecodeError:
                                pass
                        json_response['result'] = parsed_result
                    except json.JSONDecodeError:
                        pass  # Keep as string if it's not valid JSON
                
                return json_response
            except Exception as e:
                logger.error(f"Failed to parse JSON response: {str(e)}")
                raise SuperfaceException(f"Failed to parse JSON response: {str(e)}")
        elif response.status_code >=500:
            raise SuperfaceException("Something went wrong in the Superface")
        elif response.status_code == 400:
            raise SuperfaceException("Incorrect request")
        elif response.status_code == 401:
            raise SuperfaceException("Please provide a valid API token")
        elif response.status_code == 403:
            raise SuperfaceException("You don't have access to this resource")
        elif response.status_code == 404:
            raise SuperfaceException("Not found")
        elif response.status_code == 405:
            raise SuperfaceException("Something went wrong in the tool use. Please retry")
        else:
            raise SuperfaceException("Something went wrong in the agent")

    def _get_headers(self, user_id: str):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "x-superface-user-id": user_id,
            "Content-Type": "application/json"
        }
    
from typing import Any, Type, Optional, Union
from pydantic import BaseModel, Field, create_model
from enum import Enum

def json_schema_to_pydantic(schema: dict[str, Any]) -> Type[BaseModel]:
    type_mapping = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    properties = schema.get("properties", {})
    required_fields = schema.get("required", [])
    model_fields = {}

    for field_name, field_props in properties.items():
        json_type = field_props.get("type", "string")
        enum_values = field_props.get("enum")
        
        # Determine field type
        if enum_values:
            field_type = Enum(f"{field_name.capitalize()}Enum", {v: v for v in enum_values})
        elif isinstance(json_type, list):
            mapped_field_types = [type_mapping.get(t, Any) for t in json_type if t != "null"]
            field_type = Union[tuple(mapped_field_types)] if mapped_field_types else Any
        else:
            field_type = type_mapping.get(json_type, Any)

        # Handle nullable and optional fields
        nullable = field_props.get("nullable", False) or (isinstance(json_type, list) and "null" in json_type)
        if nullable:
            field_type = Optional[field_type]
        
        # Set default value
        default_value = field_props.get("default", None if field_name not in required_fields else ...)
        
        # Create field with metadata
        model_fields[field_name] = (field_type, Field(
            default_value, 
            description=field_props.get("title", "")
        ))

    return create_model(schema.get("title", "Schema"), **model_fields)

"""
Exception raised by the Superface client.
"""
class SuperfaceException(Exception):
  pass