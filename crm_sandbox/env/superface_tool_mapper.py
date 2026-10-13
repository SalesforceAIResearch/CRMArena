from typing import Any, Callable, Dict, List, Optional, Type, Union
from pydantic import BaseModel, Field, create_model
from enum import Enum
import logging
import types

logger = logging.getLogger(__name__)

def map_superface_tool_to_function(tool: 'SuperfaceTool') -> Callable:
    """
    Maps a SuperfaceTool to a function with an __info__ property that describes its arguments and return type.
    
    Args:
        tool: A SuperfaceTool instance containing name, description, input schema and perform function
        
    Returns:
        A function that wraps the tool's perform function and includes metadata about its parameters and return type
    """
    def wrapped_function(**kwargs):
        # Remove sf_connector from arguments if present
        if 'sf_connector' in kwargs:
            del kwargs['sf_connector']
        return tool.perform(arguments=kwargs)
    
    # Create the function info dictionary using the current descriptor format
    function_info = {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }
    
    # Map the input schema to function parameters
    if hasattr(tool, 'input_schema_raw'):
        schema = tool.input_schema_raw
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        
        # Convert each property to the function info format
        for prop_name, prop_schema in properties.items():
            param_info = {
                "type": prop_schema.get("type", "string"),
                "description": prop_schema.get("description", "")
            }
            
            # Handle array types
            if isinstance(param_info["type"], list) and "array" in param_info["type"]:
                param_info["type"] = "array"
                items = prop_schema.get("items")
                if items is None:
                    # Default to array of strings if items is not defined
                    param_info["items"] = {
                        "type": "string"
                    }
                else:
                    param_info["items"] = items
                    # Ensure items has a type
                    if "type" not in param_info["items"]:
                        param_info["items"]["type"] = "string"
            elif param_info["type"] == "array":
                items = prop_schema.get("items")
                if items is None:
                    # Default to array of strings if items is not defined
                    param_info["items"] = {
                        "type": "string"
                    }
                else:
                    param_info["items"] = items
                    # Ensure items has a type
                    if "type" not in param_info["items"]:
                        param_info["items"]["type"] = "string"
            
            function_info["function"]["parameters"]["properties"][prop_name] = param_info
        
        # Add required fields
        function_info["function"]["parameters"]["required"] = required
    
    # Add the info property to the function
    wrapped_function.__info__ = function_info
    
    # Set the function name dynamically
    wrapped_function.__name__ = tool.name
    
    logger.debug(f"Wrapped function: {wrapped_function}")
    
    return wrapped_function 