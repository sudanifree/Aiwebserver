from __future__ import annotations

import re
from typing import Any, Dict, Optional
import graphene

from .registry import register_tool, _operation_ids
from .schemas import GraphQLRequest
from .schema_converter import pydantic_to_json_schema, resolve_schema_refs


def introspect_graphql_schema(schema: graphene.Schema):
    """
    Introspect the GraphQL schema and register endpoints in the OpenAPI registry.
    This bridges the 'living code' (GraphQL) to the OpenAPI spec.
    """
    # Graphene schema introspection
    graphql_schema = schema.graphql_schema
    query_type = graphql_schema.query_type

    if not query_type:
        return

    # We register the main /graphql endpoint once
    register_tool(
        path="/graphql",
        method="POST",
        operation_id="graphql_query",
        summary="GraphQL Endpoint",
        description="Execute arbitrary GraphQL queries against the system schema.",
        request_model=GraphQLRequest,
        tags=["graphql"]
    )


def _flask_to_openapi_path(flask_path: str) -> str:
    """Convert Flask path syntax to OpenAPI path syntax."""
    # Handles <converter:variable> -> {variable} and <variable> -> {variable}
    return re.sub(r'<(?:\w+:)?(\w+)>', r'{\1}', flask_path)


def _get_openapi_metadata(func: Any) -> Optional[Dict[str, Any]]:
    """Recursively find _openapi_metadata in wrapped functions."""
    # Check current function
    metadata = getattr(func, "_openapi_metadata", None)
    if metadata:
        return metadata

    # Check __wrapped__ (standard for @wraps)
    if hasattr(func, "__wrapped__"):
        return _get_openapi_metadata(func.__wrapped__)

    return None


def introspect_flask_app(app: Any):
    """
    Introspect the Flask application to find routes decorated with @validate_request
    and register them in the OpenAPI registry.
    """
    registered_ops = set()
    for rule in app.url_map.iter_rules():
        view_func = app.view_functions.get(rule.endpoint)
        if not view_func:
            continue

        # Check for our decorator's metadata recursively
        metadata = _get_openapi_metadata(view_func)

        if metadata:
            if metadata.get("exclude_from_spec"):
                continue

            op_id = metadata["operation_id"]

            # Register the tool with real path and method from Flask
            for method in rule.methods:
                if method in ("OPTIONS", "HEAD"):
                    continue

                # Create a unique key for this path/method/op combination if needed,
                # but operationId must be unique globally.
                # If the same function is mounted on multiple paths, we append a suffix
                path = _flask_to_openapi_path(str(rule))

                # Check if this operation (path + method) is already registered
                op_key = f"{method}:{path}"
                if op_key in registered_ops:
                    continue

                # Determine tags - create a copy to avoid mutating shared metadata
                tags = list(metadata.get("tags") or ["rest"])
                if path.startswith("/mcp/"):
                    # For MCP endpoints, we want them exclusively in the 'mcp' tag section
                    tags = ["mcp"]

                # Ensure unique operationId
                original_op_id = op_id
                unique_op_id = op_id

                # Semantic naming strategy for duplicates
                if unique_op_id in _operation_ids:
                    # Construct a semantic suffix to replace numeric ones
                    # Priority: /mcp/ prefix and HTTP method
                    suffix = ""
                    if path.startswith("/mcp/"):
                        suffix = "_mcp"
                    
                    if method.upper() == "POST":
                        suffix += "_post"
                    elif method.upper() == "GET":
                        suffix += "_get"
                    
                    if suffix:
                        candidate = f"{op_id}{suffix}"
                        if candidate not in _operation_ids:
                            unique_op_id = candidate

                # Fallback to numeric suffixes if semantic naming didn't ensure uniqueness
                count = 1
                while unique_op_id in _operation_ids:
                    unique_op_id = f"{op_id}_{count}"
                    count += 1

                # Filter path_params to only include those that are actually in the path
                path_params = metadata.get("path_params")
                if path_params:
                    path_params = [
                        p for p in path_params
                        if f"{{{p['name']}}}" in path
                    ]

                # Auto-generate query_params from request_model for GET requests
                query_params = metadata.get("query_params")
                if method == 'GET' and not query_params and metadata.get("request_model"):
                    try:
                        schema = pydantic_to_json_schema(metadata["request_model"])
                        defs = schema.get("$defs", {})
                        properties = schema.get("properties", {})
                        query_params = []
                        for name, prop in properties.items():
                            is_required = name in schema.get("required", [])
                            # Resolve references to inlined definitions (preserving Enums)
                            resolved_prop = resolve_schema_refs(prop, defs)
                            # Create param definition
                            param_def = {
                                "name": name,
                                "in": "query",
                                "required": is_required,
                                "description": prop.get("description", ""),
                                "schema": resolved_prop
                            }
                            # Remove description from schema to avoid duplication
                            if "description" in param_def["schema"]:
                                del param_def["schema"]["description"]
                            query_params.append(param_def)
                    except Exception:
                        pass  # Fallback to empty if schema generation fails

                register_tool(
                    path=path,
                    method=method,
                    operation_id=unique_op_id,
                    original_operation_id=original_op_id if unique_op_id != original_op_id else None,
                    summary=metadata["summary"],
                    description=metadata["description"],
                    request_model=metadata.get("request_model"),
                    response_model=metadata.get("response_model"),
                    path_params=path_params,
                    query_params=query_params,
                    tags=tags,
                    allow_multipart_payload=metadata.get("allow_multipart_payload", False),
                    response_content_types=metadata.get("response_content_types"),
                    links=metadata.get("links")
                )
                registered_ops.add(op_key)
