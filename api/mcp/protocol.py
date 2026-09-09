"""
JSON-RPC 2.0 and Model Context Protocol (MCP) data structures.
Follows the official MCP specification (2025-03-26).
"""

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field

# MCP Protocol Versions
MCP_PROTOCOL_VERSION_2026_07_28 = (
    "2026-07-28"  # Current 2026 specification (Stateless core)
)
MCP_PROTOCOL_VERSION_2025_11_25 = "2025-11-25"
MCP_PROTOCOL_VERSION_2025_06_18 = "2025-06-18"
MCP_PROTOCOL_VERSION_2025_03_26 = "2025-03-26"
MCP_PROTOCOL_VERSION_2024_11_05 = "2024-11-05"

LATEST_PROTOCOL_VERSION = MCP_PROTOCOL_VERSION_2026_07_28

SUPPORTED_PROTOCOL_VERSIONS = [
    MCP_PROTOCOL_VERSION_2026_07_28,
    MCP_PROTOCOL_VERSION_2025_11_25,
    MCP_PROTOCOL_VERSION_2025_06_18,
    MCP_PROTOCOL_VERSION_2025_03_26,
    MCP_PROTOCOL_VERSION_2024_11_05,
]

# JSON-RPC 2.0 Error Codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class JSONRPCError(BaseModel):
    code: int
    message: str
    data: Optional[Any] = None


class JSONRPCRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Union[str, int]] = None
    method: str
    params: Optional[Union[Dict[str, Any], List[Any]]] = None


class JSONRPCResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Union[str, int]] = None
    result: Optional[Any] = None
    error: Optional[JSONRPCError] = None


class ToolDefinition(BaseModel):
    name: str
    description: str
    inputSchema: Dict[str, Any] = Field(default_factory=dict)


class ResourceDefinition(BaseModel):
    uri: str
    name: str
    description: Optional[str] = None
    mimeType: Optional[str] = "text/plain"


class PromptArgument(BaseModel):
    name: str
    description: Optional[str] = None
    required: bool = False


class PromptDefinition(BaseModel):
    name: str
    description: Optional[str] = None
    arguments: Optional[List[PromptArgument]] = None


def make_success_response(
    req_id: Optional[Union[str, int]], result: Any
) -> Dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": result,
    }


def make_error_response(
    req_id: Optional[Union[str, int]],
    code: int,
    message: str,
    data: Optional[Any] = None,
) -> Dict[str, Any]:
    err: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": err,
    }


def make_tool_result(text: str, is_error: bool = False) -> Dict[str, Any]:
    """Formats standard MCP tool execution content."""
    res = {
        "content": [
            {
                "type": "text",
                "text": text,
            }
        ]
    }
    if is_error:
        res["isError"] = True
    return res
