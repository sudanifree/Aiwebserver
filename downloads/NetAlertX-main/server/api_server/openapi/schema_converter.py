from __future__ import annotations

from typing import Dict, Any, Optional, Type, List
from pydantic import BaseModel
from .schemas import ErrorResponse, BaseResponse


def pydantic_to_json_schema(model: Type[BaseModel], mode: str = "validation") -> Dict[str, Any]:
    """
    Convert a Pydantic model to JSON Schema (OpenAPI 3.1 compatible).

    Uses Pydantic's built-in schema generation which produces
    JSON Schema Draft 2020-12 compatible output.

    Args:
        model: Pydantic BaseModel class
        mode: Schema mode - "validation" (for inputs) or "serialization" (for outputs)

    Returns:
        JSON Schema dictionary
    """
    # Pydantic v2 uses model_json_schema()
    schema = model.model_json_schema(mode=mode)

    # Remove $defs if empty (cleaner output)
    if "$defs" in schema and not schema["$defs"]:
        del schema["$defs"]

    return schema


def build_parameters(entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build OpenAPI parameters array from path and query params."""
    parameters = []

    # Path parameters
    for param in entry.get("path_params", []):
        parameters.append({
            "name": param["name"],
            "in": "path",
            "required": True,
            "description": param.get("description", ""),
            "schema": param.get("schema", {"type": "string"})
        })

    # Query parameters
    for param in entry.get("query_params", []):
        parameters.append({
            "name": param["name"],
            "in": "query",
            "required": param.get("required", False),
            "description": param.get("description", ""),
            "schema": param.get("schema", {"type": "string"})
        })

    return parameters


def extract_definitions(schema: Dict[str, Any], definitions: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively extract $defs from a schema and move them to the definitions dict.
    Also rewrite $ref to point to #/components/schemas/.
    """
    if not isinstance(schema, dict):
        return schema

    # Extract definitions
    if "$defs" in schema:
        for name, definition in schema["$defs"].items():
            # Recursively process the definition itself before adding it
            definitions[name] = extract_definitions(definition, definitions)
        del schema["$defs"]

    # Rewrite references
    if "$ref" in schema and schema["$ref"].startswith("#/$defs/"):
        ref_name = schema["$ref"].split("/")[-1]
        schema["$ref"] = f"#/components/schemas/{ref_name}"

    # Recursively process properties
    for key, value in schema.items():
        if isinstance(value, dict):
            schema[key] = extract_definitions(value, definitions)
        elif isinstance(value, list):
            schema[key] = [extract_definitions(item, definitions) for item in value]

    return schema


def build_request_body(
    model: Optional[Type[BaseModel]],
    definitions: Dict[str, Any],
    allow_multipart_payload: bool = False
) -> Optional[Dict[str, Any]]:
    """Build OpenAPI requestBody from Pydantic model."""
    if model is None:
        return None

    schema = pydantic_to_json_schema(model)
    schema = extract_definitions(schema, definitions)

    content = {
        "application/json": {
            "schema": schema
        }
    }

    if allow_multipart_payload:
        content["multipart/form-data"] = {
            "schema": schema
        }

    return {
        "required": True,
        "content": content
    }


def strip_validation(schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively remove validation constraints from a JSON schema.
    Keeps structure and descriptions, but removes pattern, minLength, etc.
    This saves context tokens for LLMs which don't validate server output.
    """
    if not isinstance(schema, dict):
        return schema

    # Keys to remove
    validation_keys = [
        "pattern", "minLength", "maxLength", "minimum", "maximum",
        "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "minItems",
        "maxItems", "uniqueItems", "minProperties", "maxProperties"
    ]

    clean_schema = {k: v for k, v in schema.items() if k not in validation_keys}

    # Recursively clean sub-schemas
    if "properties" in clean_schema:
        clean_schema["properties"] = {
            k: strip_validation(v) for k, v in clean_schema["properties"].items()
        }

    if "items" in clean_schema:
        clean_schema["items"] = strip_validation(clean_schema["items"])

    if "allOf" in clean_schema:
        clean_schema["allOf"] = [strip_validation(x) for x in clean_schema["allOf"]]

    if "anyOf" in clean_schema:
        clean_schema["anyOf"] = [strip_validation(x) for x in clean_schema["anyOf"]]

    if "oneOf" in clean_schema:
        clean_schema["oneOf"] = [strip_validation(x) for x in clean_schema["oneOf"]]

    if "$defs" in clean_schema:
        clean_schema["$defs"] = {
            k: strip_validation(v) for k, v in clean_schema["$defs"].items()
        }

    if "additionalProperties" in clean_schema and isinstance(clean_schema["additionalProperties"], dict):
        clean_schema["additionalProperties"] = strip_validation(clean_schema["additionalProperties"])

    return clean_schema


def resolve_schema_refs(schema: Dict[str, Any], definitions: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively resolve $ref in schema by inlining the definition.
    Useful for standalone schema parts like query parameters where global definitions aren't available.
    """
    if not isinstance(schema, dict):
        return schema

    if "$ref" in schema:
        ref = schema["$ref"]
        # Handle #/$defs/Name syntax
        if ref.startswith("#/$defs/"):
            def_name = ref.split("/")[-1]
            if def_name in definitions:
                # Inline the definition (and resolve its refs recursively)
                inlined = resolve_schema_refs(definitions[def_name], definitions)
                # Merge any extra keys from the original schema (e.g. description override)
                # Schema keys take precedence over definition keys
                return {**inlined, **{k: v for k, v in schema.items() if k != "$ref"}}

    # Recursively resolve properties
    resolved = {}
    for k, v in schema.items():
        if k == "items":
            resolved[k] = resolve_schema_refs(v, definitions)
        elif k == "properties":
            resolved[k] = {pk: resolve_schema_refs(pv, definitions) for pk, pv in v.items()}
        elif k in ("allOf", "anyOf", "oneOf"):
            resolved[k] = [resolve_schema_refs(i, definitions) for i in v]
        else:
            resolved[k] = v

    return resolved


def build_responses(
    response_model: Optional[Type[BaseModel]],
    definitions: Dict[str, Any],
    response_content_types: Optional[List[str]] = None,
    links: Optional[Dict[str, Any]] = None,
    method: str = "post"
) -> Dict[str, Any]:
    """Build OpenAPI responses object."""
    responses = {}

    # Use a fresh list for response content types to avoid a shared mutable default.
    if response_content_types is None:
        response_content_types = ["application/json"]
    else:
        # Copy provided list to ensure each call gets its own list
        response_content_types = list(response_content_types)

    # Success response (200)
    effective_model = response_model or BaseResponse
    schema = strip_validation(pydantic_to_json_schema(effective_model, mode="serialization"))
    schema = extract_definitions(schema, definitions)

    content = {}
    for ct in response_content_types:
        if ct == "application/json":
            content[ct] = {"schema": schema}
        else:
            # For non-JSON types like CSV, we don't necessarily use the JSON schema
            content[ct] = {"schema": {"type": "string", "format": "binary"}}

    response_obj = {
        "description": "Successful response",
        "content": content
    }
    if links:
        response_obj["links"] = links
    responses["200"] = response_obj

    # Standard error responses
    error_configs = {
        "400": ("Invalid JSON", "Request body must be valid JSON"),
        "401": ("Unauthorized", None),
        "403": ("Forbidden", "ERROR: Not authorized"),
        "404": ("API route not found", "The requested URL /example/path was not found on the server."),
        "422": ("Validation Error", None),
        "500": ("Internal Server Error", "Something went wrong on the server")
    }

    for code, (error_val, message_val) in error_configs.items():
        # Generate a fresh schema for each error to customize examples
        error_schema_raw = strip_validation(pydantic_to_json_schema(ErrorResponse, mode="serialization"))
        error_schema = extract_definitions(error_schema_raw, definitions)

        # Inject status-specific example
        if "examples" in error_schema and len(error_schema["examples"]) > 0:
            example = {
                "success": False,
                "error": error_val
            }
            if message_val:
                example["message"] = message_val

            if code == "422":
                example["error"] = "Validation Error: Input should be a valid string"
                example["details"] = [
                    {
                        "input": "invalid_value",
                        "loc": ["field_name"],
                        "msg": "Input should be a valid string",
                        "type": "string_type",
                        "url": "https://errors.pydantic.dev/2.12/v/string_type"
                    }
                ]

            error_schema["examples"] = [example]

        responses[code] = {
            "description": error_val,
            "content": {
                "application/json": {
                    "schema": error_schema
                }
            }
        }

    return responses
